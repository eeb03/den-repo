"""
Known-geometry calibration through the PRODUCT path on real BAM data
(`scripts/bam_calibration_product_path.py`). Skipped when the 889 MB Pk266
archive is not present (Harvard Dataverse doi:10.7910/DVN/FCMUJQ, CC0).

Pins what the run established: the DEPTH_CALIBRATION declaration, fitted only on
the four back-wall steps, is accepted as redundant, the depths read back from
STORAGE equal the fit's own conversion, and the four ducts land within 10 mm of
the drawn top at both antennas.
"""
from pathlib import Path

import pytest

ARCHIVE = Path("datasets/raw/bam_concrete/Pk266_Dataset.zip")
pytestmark = pytest.mark.skipif(not ARCHIVE.exists(), reason="BAM Pk266 archive not held")


@pytest.mark.parametrize("scan", ["1_5_GHz_Rot00", "2_6_GHz_Rot00"])
def test_backwall_calibration_puts_ducts_within_10_mm_through_the_product_path(scan):
    from scripts.bam_calibration_product_path import run

    r = run("Pk266", scan)
    assert r["status"] == "calibrated", r
    assert r["fit"]["redundant"] is True
    assert len(r["ducts"]) == 4
    for d in r["ducts"]:
        assert d["stored_depth_mm"] == pytest.approx(d["fit_depth_mm"], abs=0.11)
        assert abs(d["err_top_mm"]) <= 10.0
    assert len({d["stored_record_derivation_id"] for d in r["ducts"]}) == 1
