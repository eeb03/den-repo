from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from schemas.subterra_record import SubterraRecord, SensorType
from schemas.survey_frame import SurveyFrame


@dataclass
class ConversionResult:
    """
    What a converter produces: the per-sample records, plus one SurveyFrame
    per acquisition unit describing the constant-per-line facts (modality,
    format, CRS, vertical axis, provenance, assumptions).

    Deliberately a plain dataclass rather than a pydantic model. A pydantic
    container would re-validate every element on construction, and a single
    SEG-Y line here is ~35,000 records (the largest is ~962,000) -- paying
    validation twice for no benefit.
    """
    records: list[SubterraRecord]
    frames: list[SurveyFrame] = field(default_factory=list)


class BaseConverter(ABC):
    """Every format converter takes a raw file and yields Universal Subterra Records."""

    format_name: str = "base"
    supported_extensions: tuple[str, ...] = ()

    @abstractmethod
    def convert(
        self, path: str | Path, dataset_id: str, sensor_type: SensorType
    ) -> list[SubterraRecord]:
        raise NotImplementedError

    def load(
        self, path: str | Path, dataset_id: str, sensor_type: SensorType, **kwargs
    ) -> ConversionResult:
        """
        Records plus frames. This is the interface new code should call.

        The default implementation delegates to `convert()` and attaches no
        frame, so converters written before frames existed keep working
        untouched -- a caller simply gets `frames == []` and can fall back
        to `database.frames_store.synthesize_frames_from_records`.

        A converter that wants to emit real frames overrides THIS method
        and makes its `convert()` return `self.load(...).records`.
        Note the one rule: an overridden `load()` must not call
        `convert()`, or the two defaults recurse indefinitely.
        """
        return ConversionResult(
            records=self.convert(path, dataset_id=dataset_id, sensor_type=sensor_type, **kwargs),
            frames=[],
        )

    def can_handle(self, path: str | Path) -> bool:
        return Path(path).suffix.lower() in self.supported_extensions


class MissingDependencyError(RuntimeError):
    """Raised when an optional format library (segyio, laspy, rasterio, obspy) isn't installed."""
    pass
