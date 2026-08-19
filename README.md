# Subterra Data Platform (SDP)

The data foundation for the Subterra AI ecosystem — downloads, validates,
standardizes, fuses, and serves multimodal underground sensing datasets
(GPR, seismic, magnetometer, ERT, gravity, LiDAR, satellite, GPS/IMU).

## Status

Core backend and data platform: complete. Ingestion across four formats and
multiple vendors, provenance-tracked preprocessing, spatial reference
handling, candidate detection, authentication/ownership, and a full Next.js
workspace UI all exist and are tested. The authoritative, evidenced status of
every work area — including what is still blocked and why — is tracked in
[`docs/roadmap.md`](docs/roadmap.md). The longer-term product vision and
phase sequence is in [`ROADMAP.md`](ROADMAP.md).

## Quickstart

```bash
git clone https://github.com/eeb03/den-repo.git
cd den-repo
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8001/api/docs
- Postgres+PostGIS: localhost:5433

(Both are shifted by one from the defaults inside the containers: Subterra
Core's own API and Postgres already hold 8000 and 5432 on the same machine.
`docker-compose.yml` is the authority for the mapping.)

`docker compose up` starts the **backend API and database only** — it does not
build or serve the frontend. To see the actual product UI (the dataset
workspace), start the frontend separately; see
[`frontend/README.md`](frontend/README.md) for the full detail:

```bash
cd frontend
corepack enable            # once
corepack pnpm install
corepack pnpm dev          # http://localhost:3000
```

Run the backend without Docker (SQLite dev mode — no `.env` required, the
default `DATABASE_URL` is already a local SQLite file):

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
datasets/          raw + processed data, organized by sensor
frontend/          Next.js workspace UI -- see frontend/README.md
ingestion/         downloader manager (resume, checksum, retry, dedupe)
converters/        per-format -> Universal Subterra Record
validators/        integrity / quality / coordinate checks
preprocessing/     noise reduction, normalization, interpolation, sync
fusion/            spatial matching + multimodal fusion samples
interpretation/    candidate generation, read-only anomaly interpretation
schemas/           Pydantic models shared across the backend and API
auth/              sessions, ownership, password reset
database/          SQLAlchemy models (Postgres/PostGIS + SQLite dev fallback)
api/               FastAPI app + routes
visualization/     Plotly viewer + thin client, served by the API
tests/             pytest suite
```

## Universal Subterra Record

Every dataset, regardless of source format, converts into one schema
(`schemas/subterra_record.py`). `position` is the authoritative spatial
field — a discriminated union (geographic / projected / odometry / none),
never an optional lat/lon — with `latitude`/`longitude` kept only as a
derived convenience view:

```
dataset_id, sensor_type, position, elevation, timestamp,
depth, signal, metadata, ground_truth, confidence
```
