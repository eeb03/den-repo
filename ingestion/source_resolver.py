"""
Turns "the thing the user pointed at" into a list of convertible sources.

A caller may hand the platform a single file, a directory, or an archive,
and a real dataset file often does not stand alone: SEG-Y lines are
accompanied by a .kmz survey track, and proprietary GPR formats keep their
header in a same-stem sibling. Before this module, converters dispatched on
one path with nothing attached to it, and sidecar discovery lived hardcoded
inside a single ingest endpoint -- so KMZ georeferencing worked for
/ingest_zip_from_url and nowhere else.

Resolution is deliberately CLASSIFYING rather than filtering. Files in
formats we recognise but cannot read are reported, not dropped, so "this
archive holds 40 IDS GeoRadar files and no adapter exists" stays
distinguishable from "this archive holds nothing of interest".

Nothing here parses or converts. It only decides what the units of work
are, and what belongs with each one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from converters.registry import classify_file, describe_unsupported, supported_extensions
from utils.logger import get_logger

logger = get_logger(__name__)

#: Sidecars identified by sharing a primary file's stem. Each carries header
#: or positioning information that is meaningless without its primary.
STEM_SIDECAR_EXTENSIONS = {".dt_info", ".rad", ".dzx", ".dzg", ".hdr", ".prj", ".aux.xml"}

#: Sidecars that describe a whole ACQUISITION rather than one file, and so
#: attach to every source they could plausibly belong to. A .kmz holds the
#: survey tracks for many SEG-Y lines at once, keyed by placemark name.
ACQUISITION_SIDECAR_EXTENSIONS = {".kmz", ".kml"}

#: Which primary formats an acquisition-level sidecar is offered to.
ACQUISITION_SIDECAR_TARGETS = {".sgy", ".segy"}

ARCHIVE_EXTENSIONS = {".zip"}


@dataclass
class ResolvedSource:
    """One convertible unit, with whatever belongs alongside it."""
    primary: Path
    kind: str                                   # "file" | "archive_member"
    sidecars: list[Path] = field(default_factory=list)
    archive_path: Path | None = None

    @property
    def stem(self) -> str:
        return self.primary.stem

    def sidecars_with_suffix(self, suffixes: set[str]) -> list[Path]:
        return [p for p in self.sidecars if p.suffix.lower() in suffixes]


@dataclass
class ResolutionResult:
    root: Path
    sources: list[ResolvedSource] = field(default_factory=list)
    recognized_unsupported: list[tuple[Path, str]] = field(default_factory=list)

    def unsupported_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _path, description in self.recognized_unsupported:
            counts[description] = counts.get(description, 0) + 1
        return counts

    @property
    def acquisition_sidecars(self) -> list[Path]:
        """Every acquisition-level sidecar found, de-duplicated, in stable order."""
        seen, out = set(), []
        for s in self.sources:
            for p in s.sidecars_with_suffix(ACQUISITION_SIDECAR_EXTENSIONS):
                if p not in seen:
                    seen.add(p)
                    out.append(p)
        return out


def _is_real_data_file(p: Path) -> bool:
    """Excludes macOS AppleDouble sidecars: Finder metadata wearing the real file's extension."""
    return p.is_file() and not p.name.startswith("._") and "__MACOSX" not in p.parts


def _walk(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if _is_real_data_file(p))


def _attach_sidecars(primaries: list[Path], all_files: list[Path]) -> dict[Path, list[Path]]:
    """
    Works out what belongs with each primary.

    Same-stem sidecars attach only to their own primary. Acquisition-level
    sidecars (.kmz) attach to every eligible primary, because one KMZ
    commonly holds the tracks for a whole directory of SEG-Y lines and which
    placemark belongs to which line is decided later, by name.
    """
    by_stem: dict[str, list[Path]] = {}
    acquisition: list[Path] = []
    for f in all_files:
        suffix = f.suffix.lower()
        if suffix in ACQUISITION_SIDECAR_EXTENSIONS:
            acquisition.append(f)
        elif suffix in STEM_SIDECAR_EXTENSIONS:
            by_stem.setdefault(f.stem, []).append(f)

    attached: dict[Path, list[Path]] = {}
    for primary in primaries:
        found = list(by_stem.get(primary.stem, []))
        if primary.suffix.lower() in ACQUISITION_SIDECAR_TARGETS:
            found.extend(acquisition)
        attached[primary] = found
    return attached


def _classify_all(files: list[Path], root: Path, kind: str,
                  archive_path: Path | None = None) -> ResolutionResult:
    supported, unsupported = [], []
    for f in files:
        classification, detail = classify_file(f)
        if classification == "supported":
            supported.append(f)
        elif classification == "recognized_unsupported":
            unsupported.append((f, detail))

    attached = _attach_sidecars(supported, files)
    return ResolutionResult(
        root=root,
        sources=[
            ResolvedSource(primary=p, kind=kind, sidecars=attached[p], archive_path=archive_path)
            for p in supported
        ],
        recognized_unsupported=unsupported,
    )


def resolve(path: str | Path, extract_to: str | Path | None = None) -> ResolutionResult:
    """
    Resolves a file, directory, or archive into convertible sources.

    Raises FileNotFoundError if the path does not exist. A path that exists
    but yields nothing readable returns an empty `sources` list with
    `recognized_unsupported` populated where applicable -- callers should
    report that distinction rather than treating both as "empty".
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Cannot resolve {path}: no such file or directory")

    if path.is_dir():
        result = _classify_all(_walk(path), root=path, kind="file")
    elif path.suffix.lower() in ARCHIVE_EXTENSIONS:
        import zipfile

        target = Path(extract_to) if extract_to else path.parent / f"{path.stem}_extracted"
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path) as zf:
            zf.extractall(target)
        result = _classify_all(_walk(target), root=target, kind="archive_member",
                               archive_path=path)
    else:
        # A single file still gets its siblings considered, so a .sgy handed
        # over directly can still find the .kmz sitting next to it.
        siblings = [p for p in sorted(path.parent.iterdir()) if _is_real_data_file(p)]
        classification, detail = classify_file(path)
        if classification == "supported":
            result = _classify_all([path] + [s for s in siblings if s != path],
                                   root=path.parent, kind="file")
            result.sources = [s for s in result.sources if s.primary == path]
        elif classification == "recognized_unsupported":
            result = ResolutionResult(root=path.parent, recognized_unsupported=[(path, detail)])
        else:
            result = ResolutionResult(root=path.parent)

    logger.info(
        f"resolve: {path.name} -> {len(result.sources)} source(s), "
        f"{len(result.recognized_unsupported)} recognised-but-unsupported "
        f"({result.unsupported_summary() or 'none'}); "
        f"{len(result.acquisition_sidecars)} acquisition sidecar(s)"
    )
    return result


def readable_formats() -> list[str]:
    """Extensions the platform can currently read, for error messages."""
    return sorted(supported_extensions())
