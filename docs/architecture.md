# Subterra Data Platform — Architecture

## Data flow

```
raw file (SEG-Y/LAS/CSV/GeoTIFF/...)
        │
        ▼
converters/registry.py  ──► picks converter by extension
        │
        ▼
converter.convert()  ──► list[SubterraRecord]   (schemas/subterra_record.py)
        │
        ▼
validators/dataset_validator.py  ──► DatasetQualityReport (score, issues)
        │
        ▼
preprocessing/pipeline.py  ──► denoise / normalize / interpolate
        │
        ▼
database/records_store.py  ──► persisted as JSONL under datasets/processed/
database/models.py::Dataset ──► metadata registered in Postgres/SQLite
        │
        ▼
fusion/sensor_fusion.py  ──► spatially clusters records across datasets
        │                    into multimodal FusionSamples
        ▼
api/routes/*.py  ──► REST surface for all of the above
```

## Why records live outside Postgres

A single LiDAR or SEG-Y file can produce hundreds of thousands to millions
of `SubterraRecord`s. Rather than exploding the relational database with
per-point rows, the metadata registry (`Dataset` table) stays small and
queryable, while the bulk record payloads live as newline-delimited JSON
under `datasets/processed/{dataset_id}.jsonl`. This is the seam to swap in
a columnar store (Parquet + DuckDB) or a time-series DB (TimescaleDB) as
volume grows — every call site goes through `database/records_store.py`,
so nothing above it has to change.

## Extending the platform

- **New file format**: add a `BaseConverter` subclass in `converters/`,
  register it in `converters/registry.py`. Nothing else changes.
- **New dataset source**: add a `BaseSourceConnector` subclass in
  `ingestion/sources.py`, register it in `SOURCE_REGISTRY`.
- **New sensor type / ground truth label**: add to the enums in
  `schemas/subterra_record.py`.
- **New API capability**: add a router module under `api/routes/` and
  include it in `api/main.py`.

## Known Phase-1 simplifications (tracked for Phase 2)

- SEG-Y coordinates are passed through from trace headers as-is; a proper
  CRS-aware reprojection (pyproj) is needed for non-lat/lon source data.
- Dataset source connectors (Zenodo/OpenTopography/USGS/NASA/ESA/Kaggle)
  are stubbed interfaces — the download *mechanics* (resume/retry/
  checksum/dedupe) are real and source-agnostic; the *search/catalog*
  logic per source is not yet implemented.
- No auth/encryption/dataset-signing yet — fine for local/dev use, not
  for a multi-user deployment.
- No PyTorch/TensorFlow DataLoader wrappers yet — `SubterraRecord` and
  `FusionSample` are the stable interfaces Phase 2 training code will
  consume.
