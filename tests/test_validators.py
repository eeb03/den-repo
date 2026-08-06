from schemas.subterra_record import SubterraRecord, SensorType
from validators.dataset_validator import validate_dataset


def _rec(**overrides) -> SubterraRecord:
    base = dict(
        dataset_id="ds1",
        sensor_type=SensorType.GPR,
        latitude=40.0,
        longitude=-105.0,
        signal=[1.0, 2.0, 3.0],
    )
    base.update(overrides)
    return SubterraRecord(**base)


def test_validate_perfect_dataset_scores_high():
    records = [_rec(timestamp="2024-01-01T00:00:00", depth=1.5) for _ in range(10)]
    report = validate_dataset(records, dataset_id="ds1")
    assert report.record_count == 10
    assert report.quality_score > 0.9
    assert report.issues == []


def test_validate_flags_null_island():
    records = [_rec(latitude=0.0, longitude=0.0) for _ in range(5)]
    report = validate_dataset(records, dataset_id="ds1")
    assert report.missing_coordinates == 5
    assert any("null-island" in issue for issue in report.issues)
    assert report.quality_score < 0.6


def test_validate_empty_dataset():
    report = validate_dataset([], dataset_id="ds1")
    assert report.record_count == 0
    assert report.quality_score == 0.0
    assert report.issues
