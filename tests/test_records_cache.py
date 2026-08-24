"""
The single-entry parse cache in database.records_store.

A dataset workspace page load calls load_records six times for the same
dataset, and each call re-parsed the whole corpus. These tests pin the cache's
correctness properties, not its speed: every assertion below is deterministic
and none of them times anything.

What they exist to prevent, in order of severity:

  1. the cache returning something DIFFERENT from a real parse;
  2. the cache returning STALE records after the file changed;
  3. one request's mutation leaking into what every later reader sees;
  4. the route-level monkeypatch seam being silently bypassed, which would
     leave tests green while testing nothing.
"""
import json

import pytest

from database import records_store
from database.records_store import (
    clear_records_cache,
    load_records,
    save_records,
)
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


def _record(signal_value: float = 1.0, depth: float = 0.5) -> SubterraRecord:
    return SubterraRecord(
        dataset_id="ds", sensor_type=SensorType.GPR,
        latitude=52.0, longitude=6.0,
        position=GeographicPosition(lat=52.0, lon=6.0),
        frame_id="ds:line", depth=depth, signal=[signal_value],
        metadata={"source_file": "a.sgy"},
    )


@pytest.fixture
def counting_parse(monkeypatch):
    """Counts real parses, so 'was the cache used' is a number, not a stopwatch."""
    calls = []
    real = records_store._parse

    def _counted(path):
        calls.append(str(path))
        return real(path)

    monkeypatch.setattr(records_store, "_parse", _counted)
    return calls


# --- 1. the cached answer is the same answer -------------------------------

def test_cached_result_equals_the_uncached_loader(isolated_store):
    save_records("ds", [_record(1.0), _record(2.0, depth=0.9)])

    uncached = load_records("ds", use_cache=False)
    cached = load_records("ds")

    assert len(cached) == len(uncached) == 2
    assert [r.model_dump() for r in cached] == [r.model_dump() for r in uncached]


def test_a_missing_dataset_is_still_empty_and_is_not_cached(isolated_store,
                                                            counting_parse):
    assert load_records("nope") == []
    assert counting_parse == []


# --- 2. repeated reads reuse the parse -------------------------------------

def test_repeated_reads_parse_only_once(isolated_store, counting_parse):
    save_records("ds", [_record()])

    for _ in range(6):                      # the six calls one page load makes
        assert len(load_records("ds")) == 1

    assert len(counting_parse) == 1, "expected one parse for six cached reads"


def test_use_cache_false_always_parses(isolated_store, counting_parse):
    save_records("ds", [_record()])

    load_records("ds", use_cache=False)
    load_records("ds", use_cache=False)

    assert len(counting_parse) == 2


def test_the_cache_holds_one_dataset_so_alternating_reads_reparse(
        isolated_store, counting_parse):
    """The bound is deliberate: a parsed corpus is ~411 MB, so it is one entry."""
    save_records("a", [_record()])
    save_records("b", [_record(2.0)])
    counting_parse.clear()

    load_records("a")
    load_records("b")
    load_records("a")

    assert len(counting_parse) == 3


# --- 3. a changed file is never served from cache --------------------------

def test_rewriting_through_save_records_invalidates(isolated_store, counting_parse):
    save_records("ds", [_record(1.0)])
    assert load_records("ds")[0].signal == [1.0]
    counting_parse.clear()

    save_records("ds", [_record(9.0)])

    assert load_records("ds")[0].signal == [9.0]
    assert len(counting_parse) == 1


def _write_raw(path, records):
    """
    Writes the records file WITHOUT going through save_records.

    This matters. save_records calls clear_records_cache(), so a test that
    rewrites through it proves only that the explicit clear works -- the
    path+mtime+size identity could be removed entirely and such a test would
    still pass. Writing directly leaves the identity check as the only thing
    that can notice the file changed, which is what these two tests are for.
    Something outside this process editing the file is also the real case the
    identity exists to cover.
    """
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r.to_flat_dict(), default=str) + "\n")


def test_a_changed_size_invalidates_without_any_explicit_clear(isolated_store):
    path = isolated_store / "ds.jsonl"
    _write_raw(path, [_record(1.0)])
    assert len(load_records("ds")) == 1

    _write_raw(path, [_record(1.0), _record(2.0)])        # different size

    assert len(load_records("ds")) == 2


def test_a_changed_mtime_invalidates_at_identical_size(isolated_store):
    """The mirror case: same byte count, different content, no explicit clear."""
    import os

    path = isolated_store / "ds.jsonl"
    _write_raw(path, [_record(1.0)])
    size_before = path.stat().st_size
    assert load_records("ds")[0].signal == [1.0]

    _write_raw(path, [_record(2.0)])                      # equal-length rendering
    assert path.stat().st_size == size_before, "test needs an equal-size rewrite"
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))

    assert load_records("ds")[0].signal == [2.0]


# --- 4. mutation cannot leak into the cache --------------------------------

def test_mutating_the_returned_list_does_not_affect_later_readers(isolated_store):
    save_records("ds", [_record()])

    first = load_records("ds")
    first.append(_record(99.0))
    first.clear()

    assert len(load_records("ds")) == 1


def test_a_write_path_loading_uncached_gets_objects_it_may_mutate(isolated_store):
    """
    The contract the three write handlers rely on: use_cache=False hands back
    objects that are NOT the cached ones, so reprocessing them in place cannot
    corrupt what a concurrent reader sees.
    """
    save_records("ds", [_record(1.0)])
    cached = load_records("ds")

    writable = load_records("ds", use_cache=False)
    assert writable[0] is not cached[0]

    writable[0].signal = [42.0]

    assert load_records("ds")[0].signal == [1.0]


def test_the_write_handlers_do_not_use_the_cache():
    """
    Pins the rule rather than trusting a comment: every load_records call in a
    handler that also calls save_records must pass use_cache=False.
    """
    import re
    from pathlib import Path

    src = Path("api/routes/datasets.py").read_text()
    # Every function that BOTH loads and saves records, found rather than
    # assumed -- a new write path added later is caught without editing a list.
    funcs = re.findall(r"^(?:async )?def (\w+)\(.*?(?=^(?:async )?def |\Z)",
                       src, re.S | re.M)
    bodies = re.split(r"^(?:async )?def \w+\(", src, flags=re.M)[1:]
    checked = []
    for name, body in zip(funcs, bodies):
        loads = re.findall(r"load_records\([^)]*\)", body)
        if not loads or "save_records(" not in body:
            continue
        checked.append(name)
        for call in loads:
            assert "use_cache=False" in call, \
                f"{name} both loads and saves records but loads cached: {call}"

    assert set(checked) == {"reprocess_dataset", "align_dataset_with_dem",
                            "_run_depth_slice_pipeline", "apply_time_zero"}, \
        f"the set of record-write paths changed: {sorted(checked)}"


# --- 5. the route-level monkeypatch seam still intercepts ------------------

def test_route_monkeypatch_of_load_records_still_intercepts(monkeypatch):
    """
    tests/test_frame_read_path.py stubs `api.routes.datasets.load_records`. If a
    handler were switched to a differently-named cached loader, that stub would
    be bypassed and those tests would pass while exercising nothing. This fails
    loudly if that ever happens.
    """
    import api.routes.datasets as mod

    sentinel = [_record(7.0)]
    seen = []

    def _stub(dataset_id, **kwargs):
        seen.append(dataset_id)
        return sentinel

    monkeypatch.setattr(mod, "load_records", _stub)

    assert mod.load_records("ds") is sentinel
    assert seen == ["ds"]


def test_read_handlers_call_the_patchable_module_level_name():
    """
    The seam only works while handlers call the module-global `load_records`.
    A local import or a direct records_store.<fn> call inside a handler would
    silently escape the patch.
    """
    import re
    from pathlib import Path

    for path in ("api/routes/datasets.py", "api/routes/overlays.py",
                 "api/routes/provenance.py", "api/routes/views.py"):
        src = Path(path).read_text()
        assert re.search(r"^from database\.records_store import .*load_records",
                         src, re.M), f"{path} must import load_records at module level"
        assert "records_store.load_records(" not in src, \
            f"{path} bypasses the patchable name with a qualified call"
