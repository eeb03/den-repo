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


def test_a_dataset_with_no_horizontal_position_is_reported_not_penalised():
    """
    M3 inverts this test's original premise. It used to assert that (0, 0)
    coordinates were "null-island, likely missing data" and cost half the
    quality score. But (0, 0) was a PLACEHOLDER converters were forced to
    invent, and a format that genuinely provides no position (IDS .dt) is
    complete as it stands. Absence is now reported as a fact about the
    dataset, not scored as a defect.
    """
    records = [_rec(latitude=0.0, longitude=0.0) for _ in range(5)]
    report = validate_dataset(records, dataset_id="ds1")
    assert report.missing_coordinates == 0
    assert any("No record carries a horizontal position" in i for i in report.issues)
    assert report.quality_score > 0.6


def test_a_dataset_claiming_geographic_coordinates_without_them_is_flagged():
    """The real defect: declaring a geographic position and not having one."""
    from schemas.spatial import GeographicPosition
    records = [_rec(latitude=41.0, longitude=15.0) for _ in range(4)]
    for r in records[:2]:
        r.position = GeographicPosition(lat=41.0, lon=15.0)
        r.latitude = None
        r.longitude = None
    report = validate_dataset(records, dataset_id="ds1")
    assert report.missing_coordinates == 2
    assert any("carry no coordinates" in issue for issue in report.issues)


def test_validate_empty_dataset():
    report = validate_dataset([], dataset_id="ds1")
    assert report.record_count == 0
    assert report.quality_score == 0.0
    assert report.issues
