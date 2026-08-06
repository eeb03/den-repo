from unittest.mock import patch, MagicMock

import pytest

from ingestion.sources import ZenodoConnector, OpenTopographyConnector, USGSConnector, SourceAPIError


def _mock_response(json_data, status_ok=True):
    resp = MagicMock()
    resp.json.return_value = json_data
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = Exception("HTTP error")
    return resp


@patch("ingestion.sources.requests.get")
def test_zenodo_search_parses_hits(mock_get):
    mock_get.return_value = _mock_response({
        "hits": {"hits": [{
            "id": 123, "doi": "10.5281/zenodo.123",
            "metadata": {"title": "GPR survey dataset", "description": "desc", "license": {"id": "cc-by-4.0"}},
            "files": [{"key": "data.sgy", "links": {"self": "https://zenodo.org/files/data.sgy"}, "size": 1000}],
            "links": {"self": "https://zenodo.org/records/123"},
        }]}
    })
    connector = ZenodoConnector()
    results = connector.search("ground penetrating radar", limit=5)
    assert len(results) == 1
    assert results[0].title == "GPR survey dataset"
    assert results[0].license == "cc-by-4.0"
    assert results[0].extra["record_id"] == 123
    assert results[0].download_url == "https://zenodo.org/files/data.sgy"


@patch("ingestion.sources.requests.get")
def test_zenodo_search_raises_on_http_failure(mock_get):
    import requests
    mock_get.side_effect = requests.RequestException("boom")
    connector = ZenodoConnector()
    with pytest.raises(SourceAPIError):
        connector.search("anything")


def test_opentopography_search_matches_known_types():
    connector = OpenTopographyConnector()
    results = connector.search("copernicus")
    assert any("COP30" in r.extra["dem_type"] or "COP90" in r.extra["dem_type"] for r in results)


def test_opentopography_get_global_dem_rejects_unknown_type():
    connector = OpenTopographyConnector()
    with pytest.raises(ValueError):
        connector.get_global_dem("NOT_A_REAL_TYPE", 0, 1, 0, 1)


@patch("ingestion.sources.requests.get")
def test_usgs_search_parses_earthquake_features(mock_get):
    mock_get.return_value = _mock_response({
        "features": [{
            "properties": {"title": "M 4.2 - offshore", "mag": 4.2, "detail": "https://example.com/detail", "time": 1234567890},
            "geometry": {"coordinates": [-120.5, 35.1, 8.3]},
        }]
    })
    connector = USGSConnector()
    results = connector.search("4.0", limit=10)
    assert len(results) == 1
    assert results[0].extra["magnitude"] == 4.2
    assert results[0].extra["latitude"] == 35.1


@patch("ingestion.sources.requests.get")
def test_usgs_bbox_query_passes_params(mock_get):
    mock_get.return_value = _mock_response({"features": []})
    connector = USGSConnector()
    connector.get_earthquakes_in_bbox(30, 40, -120, -110, min_magnitude=3.0)
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["minlatitude"] == 30
    assert kwargs["params"]["minmagnitude"] == 3.0
