"""
Tests for Self-Supervised GPR Encoder V1's corpus discovery, licensing
filter, site-split integrity, reserved-site isolation, and window
extraction.

Real, on-disk GPR data for everything discovery-related: this module's own
value is that it describes what is REALLY held, so a synthetic fixture
would test nothing about the actual corpus. Synthetic-only for the parts
that need a specific, unusual shape (`build_window_index`'s remainder
handling).
"""
from __future__ import annotations

from schemas.ssl_gpr import LicensePool, SiteExposure, SiteSplit, SSLSourceFile
from training import ssl_corpus


class TestDiscovery:
    def test_discovers_real_files_across_every_non_reserved_dataset(self):
        files = ssl_corpus.discover_source_files(commercial_only=False)
        found = {f.dataset_id for f in files}
        assert {"bam-concrete-gpr", "4tu-nl-utility", "tu1208-ifsttar",
                "hillside-lancaster", "testum"} <= found

    def test_every_source_file_has_a_positive_trace_and_sample_count(self):
        for f in ssl_corpus.discover_source_files(commercial_only=False):
            assert f.n_traces > 0
            assert f.n_samples > 0


class TestLicensingFilter:
    def test_commercial_only_excludes_grimsel(self):
        files = ssl_corpus.discover_source_files(commercial_only=True)
        assert not any(f.dataset_id == "grimsel-au-tunnel" for f in files)

    def test_commercial_only_excludes_every_research_only_pool_entry(self):
        files = ssl_corpus.discover_source_files(commercial_only=True)
        assert all(f.license_pool == LicensePool.COMMERCIAL_COMPATIBLE for f in files)

    def test_full_audit_includes_grimsel_explicitly_labelled_research_only(self):
        files = ssl_corpus.discover_source_files(commercial_only=False)
        grimsel = [f for f in files if f.dataset_id == "grimsel-au-tunnel"]
        assert grimsel, "the real Grimsel file should be discoverable when not filtered"
        assert grimsel[0].license_pool == LicensePool.RESEARCH_ONLY
        assert grimsel[0].commercial_use_permitted is False

    def test_every_commercial_compatible_file_has_a_recorded_license(self):
        for f in ssl_corpus.discover_source_files(commercial_only=True):
            assert f.license
            assert f.commercial_use_permitted is True


class TestSiteSplitIntegrity:
    def test_no_site_id_appears_in_two_different_fourtu_splits(self):
        files = [f for f in ssl_corpus.discover_source_files(commercial_only=True)
                 if f.dataset_id == "4tu-nl-utility"]
        by_site: dict[str, set] = {}
        for f in files:
            by_site.setdefault(f.site_id, set()).add(f.split)
        for site, splits in by_site.items():
            assert len(splits) == 1, f"site {site} appears in multiple splits: {splits}"

    def test_fourtu_reserved_and_validation_sites_are_disjoint(self):
        assert not (set(ssl_corpus.FOURTU_RESERVED_SITES) & set(ssl_corpus.FOURTU_VALIDATION_SITES))

    def test_every_fourtu_site_is_assigned_a_split(self):
        files = [f for f in ssl_corpus.discover_source_files(commercial_only=True)
                 if f.dataset_id == "4tu-nl-utility"]
        assert all(f.split is not None for f in files)

    def test_reserved_fourtu_sites_carry_unseen_site_exposure(self):
        files = [f for f in ssl_corpus.discover_source_files(commercial_only=True)
                 if f.dataset_id == "4tu-nl-utility" and f.site_id.replace("4tu-", "") in ssl_corpus.FOURTU_RESERVED_SITES]
        assert files
        assert all(f.exposure == SiteExposure.UNSEEN_SITE for f in files)

    def test_single_site_datasets_split_at_file_level_not_site_level(self):
        """TU1208/Hillside have one real site; both a train and a validation file must exist for it."""
        for dataset_id in ("tu1208-ifsttar", "hillside-lancaster"):
            files = [f for f in ssl_corpus.discover_source_files(commercial_only=True)
                     if f.dataset_id == dataset_id]
            splits = {f.split for f in files}
            assert SiteSplit.TRAIN in splits and SiteSplit.VALIDATION in splits
            # single site -> exposure is explicitly NOT unseen-site
            assert all(f.exposure == SiteExposure.UNSEEN_LABELS_SEEN_ACQUISITION for f in files)


class TestReservedSiteIsolation:
    def test_testum_is_reserved_in_full(self):
        files = [f for f in ssl_corpus.discover_source_files(commercial_only=True)
                 if f.dataset_id == "testum"]
        assert files
        assert all(f.split == SiteSplit.RESERVED for f in files)
        assert all(f.exposure == SiteExposure.UNSEEN_SITE for f in files)

    def test_reserved_datasets_are_never_returned_as_train_or_validation(self):
        files = ssl_corpus.discover_source_files(commercial_only=True)
        reserved_ids = set(ssl_corpus.RESERVED_DATASETS)
        for f in files:
            if f.dataset_id in reserved_ids:
                assert f.split == SiteSplit.RESERVED


class TestWindowExtraction:
    def test_window_index_only_yields_whole_windows(self):
        sf = SSLSourceFile(
            dataset_id="d", site_id="s", survey_id="sv", source_file="f", reader="segy_le",
            n_traces=130, n_samples=300, license="CC0-1.0", commercial_use_permitted=True,
            license_pool=LicensePool.COMMERCIAL_COMPATIBLE, split=SiteSplit.TRAIN,
            exposure=SiteExposure.UNSEEN_LABELS_SEEN_ACQUISITION,
        )
        windows = ssl_corpus.build_window_index([sf], trace_window=64, sample_window=128)
        # 130 // 64 = 2 whole trace-windows; 300 // 128 = 2 whole sample-windows -> 4 windows
        assert len(windows) == 4
        for w in windows:
            assert w.trace_end - w.trace_start + 1 == 64
            assert w.sample_end - w.sample_start + 1 == 128
            assert w.trace_end < sf.n_traces
            assert w.sample_end < sf.n_samples

    def test_a_file_smaller_than_one_window_yields_no_windows(self):
        sf = SSLSourceFile(
            dataset_id="d", site_id="s", survey_id="sv", source_file="f", reader="segy_le",
            n_traces=10, n_samples=10, license="CC0-1.0", commercial_use_permitted=True,
            license_pool=LicensePool.COMMERCIAL_COMPATIBLE, split=SiteSplit.TRAIN,
            exposure=SiteExposure.UNSEEN_LABELS_SEEN_ACQUISITION,
        )
        assert ssl_corpus.build_window_index([sf]) == []

    def test_windows_carry_the_source_files_split_and_licensing(self):
        sf = SSLSourceFile(
            dataset_id="d", site_id="s", survey_id="sv", source_file="f", reader="segy_le",
            n_traces=64, n_samples=128, license="CC-BY-4.0", commercial_use_permitted=True,
            license_pool=LicensePool.COMMERCIAL_COMPATIBLE, split=SiteSplit.VALIDATION,
            exposure=SiteExposure.UNSEEN_SITE,
        )
        [w] = ssl_corpus.build_window_index([sf])
        assert w.split == SiteSplit.VALIDATION
        assert w.exposure == SiteExposure.UNSEEN_SITE
        assert w.license == "CC-BY-4.0"

    def test_read_window_returns_real_nonconstant_amplitude_for_each_reader(self):
        """One real window per reader, materialised from the real corpus -- proves the dispatch actually reads real data, not a stub."""
        files = ssl_corpus.discover_source_files(commercial_only=True)
        windows = ssl_corpus.build_window_index(files)
        seen_readers = set()
        for w in windows:
            if w.reader in seen_readers:
                continue
            arr = ssl_corpus.read_window(w)
            assert arr.shape == (w.sample_end - w.sample_start + 1, w.trace_end - w.trace_start + 1)
            assert arr.std() > 0, f"{w.reader}: window is constant -- not real signal"
            seen_readers.add(w.reader)
        assert seen_readers == {"segy_le", "gssi_dzt", "mala_rd3", "bam_npy_yslice"}


class TestCorpusAudit:
    def test_audit_reports_every_discovered_dataset_exactly_once(self):
        rows = ssl_corpus.audit_corpus()
        ids = [r["dataset_id"] for r in rows]
        assert len(ids) == len(set(ids))
        assert "grimsel-au-tunnel" in ids  # included in the full audit, just not the commercial pool

    def test_audit_row_counts_match_direct_discovery(self):
        rows = {r["dataset_id"]: r for r in ssl_corpus.audit_corpus()}
        files = ssl_corpus.discover_source_files(commercial_only=False)
        by_dataset: dict[str, int] = {}
        for f in files:
            by_dataset[f.dataset_id] = by_dataset.get(f.dataset_id, 0) + 1
        for dataset_id, n in by_dataset.items():
            assert rows[dataset_id]["n_source_files_or_lines"] == n
