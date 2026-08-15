"""
The candidate path shares the parsed corpus instead of parsing its own.

WHAT THIS FIXES, AND WHY IT WAS SAFE TO. `api.candidates` passed
`use_cache=False` on two READ paths. The cache's contract reserves that flag for
callers who intend to MUTATE what they get back, and the candidate path mutates
nothing -- `interpretation.anomaly_candidates` is a read-only interpretation
layer by design. The flag therefore bought no safety and cost a second full
parse.

WHAT THAT COST, MEASURED. A 157,040-record corpus materialises ~384 MB of Python
objects (2,565 bytes per record). The radargram page asks for the trace grid and
the candidates at once, so the dataset was materialised TWICE concurrently. The
damage is superlinear rather than merely doubled: the same parse takes ~4 s with
nothing else resident and ~14-17 s with another copy alive, because the second
allocation runs against an allocator and collector already carrying the first.
That -- not the cache's one-entry bound -- is why Stage 15 saw two concurrent
consumers take ~66 s each. Both wanted the SAME dataset, so a size bound could
not have been what they collided on.

These tests pin the behaviour rather than the timings: "was the work done twice"
is a parse count, and a count does not flake on a loaded machine.
"""
import threading

import pytest

from api import candidates as candidate_service
from database import records_store
from database.records_store import clear_records_cache, load_records, save_records
from schemas.spatial import GeographicPosition
from schemas.subterra_record import SensorType, SubterraRecord


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    from configs import settings as settings_mod
    monkeypatch.setattr(type(settings_mod.settings), "processed_dir",
                        property(lambda self: tmp_path))
    clear_records_cache()
    yield tmp_path
    clear_records_cache()


@pytest.fixture
def counting_parse(monkeypatch):
    """Counts real parses, so cache use is a number rather than a stopwatch."""
    calls = []
    real = records_store._parse

    def _counted(path):
        calls.append(str(path))
        return real(path)

    monkeypatch.setattr(records_store, "_parse", _counted)
    return calls


def _record(trace: int, sample: int, value: float = 1.0) -> SubterraRecord:
    """
    One preprocessed GPR sample.

    `anomaly_reliable` is what marks a record as having been through
    trace-local anomaly preprocessing, which is what the candidate path
    requires before it will read `signal` as a z-score.
    """
    return SubterraRecord(
        dataset_id="ds", sensor_type=SensorType.GPR,
        latitude=52.0, longitude=6.0,
        position=GeographicPosition(lat=52.0, lon=6.0),
        frame_id="ds:line", depth=0.01 * (sample + 1), signal=[value],
        metadata={"source_file": "line.sgy", "trace_index": trace,
                  "sample_index": sample, "anomaly_reliable": True},
    )


def _line(n_traces: int = 12, n_samples: int = 12) -> list[SubterraRecord]:
    return [_record(t, s) for t in range(n_traces) for s in range(n_samples)]


@pytest.fixture
def no_declarations(monkeypatch):
    """`generate` reads the spatial declaration log; these tests have no database."""
    monkeypatch.setattr(candidate_service, "_newest_declaration_at",
                        lambda db, dataset_id: None)


# ---------------------------------------------------------------------------
# the redundant parse is gone
# ---------------------------------------------------------------------------

def test_two_consumers_of_one_dataset_parse_it_once(isolated_store, counting_parse):
    """
    The radargram page's two requests, in the order the page issues them.

    Before this change the candidate path bypassed the cache and this was two
    parses of the same file.
    """
    save_records("ds", _line())
    counting_parse.clear()

    load_records("ds")                                   # what trace_grid does
    candidate_service.current(db=None, dataset_id="ds")  # what the viewer does

    assert len(counting_parse) == 1, "the candidate path must reuse the parsed corpus"


def test_generation_reuses_the_parsed_corpus(isolated_store, counting_parse,
                                             no_declarations):
    save_records("ds", _line())
    counting_parse.clear()

    load_records("ds")
    candidate_service.generate(db=None, dataset_id="ds")

    assert len(counting_parse) == 1


def test_repeated_candidate_reads_do_not_reparse(isolated_store, counting_parse,
                                                 no_declarations):
    """
    A generated set first: `current` short-circuits to BLOCKED before touching
    records when none exists, so without one this would assert nothing.
    """
    save_records("ds", _line())
    candidate_service.generate(db=None, dataset_id="ds")
    clear_records_cache()          # start cold, so the count means something
    counting_parse.clear()

    for _ in range(5):
        candidate_service.current(db=None, dataset_id="ds")

    assert len(counting_parse) == 1, "five reads must share one parse"


def test_concurrent_consumers_parse_once(isolated_store, counting_parse,
                                        no_declarations):
    """
    The production path IS concurrent -- FastAPI runs sync handlers in a
    threadpool and the page issues both requests together.
    """
    save_records("ds", _line())
    candidate_service.generate(db=None, dataset_id="ds")
    clear_records_cache()          # both consumers arrive cold, as on a page load
    counting_parse.clear()
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def grid():
        try:
            barrier.wait()
            load_records("ds")
        except BaseException as exc:  # noqa: BLE001 -- surfaced below
            errors.append(exc)

    def candidates():
        try:
            barrier.wait()
            candidate_service.current(db=None, dataset_id="ds")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=grid), threading.Thread(target=candidates)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(counting_parse) == 1, "concurrent consumers must not each parse"


# ---------------------------------------------------------------------------
# sharing the corpus must not let one consumer corrupt another
# ---------------------------------------------------------------------------

def test_candidate_generation_does_not_mutate_the_records(isolated_store,
                                                         no_declarations):
    """
    THE PRECONDITION FOR SHARING AT ALL.

    Cached records are handed to every later reader, so a consumer that
    modified them would corrupt what the report, the trace grid and the
    provenance projection all see. Verified by hashing every record before and
    after a real generation run rather than by trusting the docstring.
    """
    save_records("ds", _line())
    records = load_records("ds")
    before = [r.model_dump_json() for r in records]

    candidate_service.generate(db=None, dataset_id="ds")

    after = [r.model_dump_json() for r in load_records("ds")]
    assert after == before, "candidate generation must leave records untouched"


def test_the_shared_list_is_a_fresh_list_each_time(isolated_store):
    """Sorting or appending to the result must not disturb the cached parse."""
    save_records("ds", _line(n_traces=3, n_samples=3))

    first = load_records("ds")
    first.reverse()

    assert len(load_records("ds")) == 9
    assert load_records("ds")[0].metadata["trace_index"] == 0


# ---------------------------------------------------------------------------
# freshness is not weakened by sharing
# ---------------------------------------------------------------------------

def test_reprocessing_invalidates_what_the_candidate_path_sees(isolated_store):
    """
    Sharing must not serve a stale corpus. `save_records` clears the cache, so
    a reprocessed dataset is re-read rather than remembered.
    """
    save_records("ds", _line(n_traces=4, n_samples=4))
    assert candidate_service.current(db=None, dataset_id="ds").status in (
        "available", "blocked")

    save_records("ds", _line(n_traces=6, n_samples=6))
    records = load_records("ds")

    assert len(records) == 36


def test_a_changed_corpus_changes_the_staleness_fingerprint(isolated_store):
    """
    The staleness rule is unchanged by sharing: it reads the CURRENT records,
    and the cache only guarantees they are the current ones.
    """
    save_records("ds", _line(n_traces=4, n_samples=4))
    first = candidate_service.current_fingerprint("ds", load_records("ds"))

    save_records("ds", _line(n_traces=5, n_samples=5))
    second = candidate_service.current_fingerprint("ds", load_records("ds"))

    assert first != second


def test_datasets_stay_isolated(isolated_store):
    """One dataset's records must never be served for another."""
    save_records("a", _line(n_traces=2, n_samples=2))
    save_records("b", _line(n_traces=3, n_samples=3))

    assert len(load_records("a")) == 4
    assert len(load_records("b")) == 9
    assert len(load_records("a")) == 4


def test_deleting_the_records_file_is_observed(isolated_store):
    save_records("ds", _line(n_traces=2, n_samples=2))
    assert load_records("ds")

    (isolated_store / "ds.jsonl").unlink()

    assert load_records("ds") == []
    assert candidate_service.current(db=None, dataset_id="ds").status == "blocked"


# ---------------------------------------------------------------------------
# the write paths still bypass, and must
# ---------------------------------------------------------------------------

def test_the_reprocessing_paths_still_take_their_own_copy():
    """
    `use_cache=False` remains correct where a handler REWRITES records and
    saves them back: handing those paths the shared objects would mutate what
    every later reader sees. Checked as source, because the failure is a flag
    quietly changed rather than a behaviour that shows up at runtime.
    """
    from pathlib import Path

    source = Path("api/routes/datasets.py").read_text()
    assert source.count("load_records(dataset_id, use_cache=False)") >= 2

    for marker in ("run_pipeline reprocesses these records",
                   "DEM alignment rewrites these records"):
        assert marker in source, f"the reason for bypassing must stay stated: {marker}"


def test_the_candidate_path_no_longer_bypasses():
    """
    Checked by parsing the CALLS rather than by searching the text: the module
    explains the old flag in a comment, and a prose mention is not a bypass.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path("api/candidates.py").read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name != "load_records":
            continue
        for keyword in node.keywords:
            assert keyword.arg != "use_cache", \
                "the candidate path reads only; bypassing costs a second full parse"
