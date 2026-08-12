# Subterra Data Platform (SDP)

The data foundation for the Subterra AI ecosystem — downloads, validates,
standardizes, fuses, and serves multimodal underground sensing datasets
(GPR, seismic, magnetometer, ERT, gravity, LiDAR, satellite, GPS/IMU).

## Status: Phase 1 (foundation build)

This is a working skeleton with real logic in the core modules, built in the
milestone order recommended by the PRD: **ingest → validate → convert →
fuse → serve → benchmark**. Later milestones (AI training pipeline,
HuggingFace export, full visualization suite, auth/security hardening) are
stubbed with clear TODOs so we can build and test each layer before moving on.

## Quickstart

```bash
bash setup.sh          # unpacks the project (if run from the bundle)
cd Subterra_Data_Platform
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8001/api/docs
- Postgres+PostGIS: localhost:5433

(Both are shifted by one from the defaults inside the containers: Subterra
Core's own API and Postgres already hold 8000 and 5432 on the same machine.
`docker-compose.yml` is the authority for the mapping.)

Run without Docker (SQLite dev mode):

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn api.main:app --reload
```

Run tests:

```bash
pytest -v
```

## Architecture

```
datasets/       raw + processed data, organized by sensor
ingestion/       downloader manager (resume, checksum, retry, dedupe)
converters/       per-format -> Universal Subterra Record
validators/       integrity / quality / coordinate checks
preprocessing/    noise reduction, normalization, interpolation, sync
fusion/           spatial matching + multimodal fusion samples
database/         SQLAlchemy models (Postgres/PostGIS + SQLite dev fallback)
api/              FastAPI app + routes
tests/            pytest suite
```

## Universal Subterra Record

Every dataset, regardless of source format, converts into one schema
(`schemas/subterra_record.py`):

```
sensor_type, latitude, longitude, elevation, timestamp,
depth, signal, metadata, ground_truth, confidence
```

## Roadmap

- [x] Folder structure + config
- [x] Database models (metadata registry)
- [x] Universal record schema
- [x] Downloader manager (checksum/resume/retry/dedupe)
- [x] Converters: CSV, SEG-Y (segyio), LAS (laspy), GeoTIFF (rasterio) — with graceful fallback if optional libs aren't installed
- [x] Validator (integrity, coordinates, missing-data, quality score)
- [x] Preprocessing pipeline (normalize, denoise, interpolate)
- [x] Sensor fusion (spatial matching across sensor types)
- [x] REST API (load/search/convert/fuse/benchmark stubs)
- [x] Docker Compose (Postgres/PostGIS + API)
- [x] Pytest suite for converters/validators/fusion
- [ ] Training pipeline (PyTorch/TF DataLoaders) — Phase 2
- [ ] Benchmark suite (detection/classification metrics) — Phase 2
- [ ] Interactive 3D viewer (Open3D) — Phase 2
- [ ] Dataset source auto-download connectors (Zenodo, OpenTopography, USGS APIs) — Phase 2
- [ ] Auth, encryption, dataset signing — Phase 2
