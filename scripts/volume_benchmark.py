"""
Volume V1 performance: build time and peak memory against survey size, and
(optionally) slice / 3D payload size and latency over HTTP for a real volume.

    python -m scripts.volume_benchmark --out evidence/volume/performance.json \
        [--http http://localhost:8001 --dataset ID --volume VID --email E --password P]

Each size is built in a fresh subprocess so peak RSS belongs to that build.
Synthetic data (random reflectors) -- the cost does not depend on content.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SIZES = [(201, 81, 512), (401, 161, 512), (601, 241, 512), (801, 321, 512)]


def one(nx, ny, nt, migration):
    code = f"""
import resource, tempfile, time, json, numpy as np
from pathlib import Path
from configs.settings import settings
tmp = tempfile.mkdtemp(); settings.data_root = Path(tmp)
for s in ('raw', 'processed', 'metadata'): (Path(tmp) / s).mkdir()
from tests.test_volume import make_grid, calibrate
rng = np.random.default_rng(0)
data = (rng.standard_normal(({nx}, {ny}, {nt})) * 0.01).astype(np.float32)
fid = make_grid('bench', data=data)
calibrate('bench', fid)
from reconstruction.volume import build
from schemas.volume import VolumeConfig
from database.volumes_store import save_volume
t = time.perf_counter(); prod, arrays = build('bench', VolumeConfig(migration='{migration}'))
tb = time.perf_counter() - t
t = time.perf_counter(); save_volume(prod, arrays); ts = time.perf_counter() - t
stored = sum(p.stat().st_size for p in Path(tmp).rglob('*.npy') if '.volumes' in str(p))
print(json.dumps({{'shape': list(prod.shape), 'voxels': int(np.prod(prod.shape)), 'migration': '{migration}',
  'build_s': round(tb, 2), 'save_s': round(ts, 2), 'stages': prod.performance,
  'peak_rss_mb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 0),
  'stored_volume_mb': round(stored / 1e6, 1), 'input_mb': round(data.nbytes / 1e6, 1)}}))
"""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    return json.loads(lines[-1]) if lines else {"error": r.stderr[-800:], "size": [nx, ny, nt]}


def http_measure(base, dataset, volume, email, password):
    import requests
    s = requests.Session()
    s.post(f"{base}/api/auth/login", json={"email": email, "password": password}).raise_for_status()
    out = {}
    meta = s.get(f"{base}/api/volumes/{dataset}/{volume}").json()
    nx, ny, nz = meta["shape"]
    for o, n in (("xy", nz), ("xz", ny), ("yz", nx)):
        times, size = [], 0
        for idx in np.linspace(0, n - 1, 12).astype(int):
            t = time.perf_counter()
            r = s.get(f"{base}/api/volumes/{dataset}/{volume}/slice", params={"orientation": o, "index": int(idx),
                                                                            "field": "response_envelope"})
            times.append((time.perf_counter() - t) * 1000)
            size = len(r.content)
        out[f"slice_{o}"] = {"payload_kb": round(size / 1024, 1), "median_ms": round(float(np.median(times)), 1),
                             "p90_ms": round(float(np.percentile(times, 90)), 1)}
    for md in (96, 160, 256):
        t = time.perf_counter()
        r = s.get(f"{base}/api/volumes/{dataset}/{volume}/render3d", params={"max_dim": md})
        out[f"render3d_max_dim_{md}"] = {"payload_kb": round(len(r.content) / 1024, 1),
                                         "ms": round((time.perf_counter() - t) * 1000, 1),
                                         "texture_shape": r.json()["shape"]}
    t = time.perf_counter()
    r = s.get(f"{base}/api/volumes/{dataset}/{volume}/voxel", params={"i": 100, "j": 80, "k": 120})
    out["voxel_ms"] = round((time.perf_counter() - t) * 1000, 1)
    out["metadata_kb"] = round(len(json.dumps(meta)) / 1024, 1)
    return out


import numpy as np  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--http")
    ap.add_argument("--dataset")
    ap.add_argument("--volume")
    ap.add_argument("--email")
    ap.add_argument("--password")
    args = ap.parse_args()
    res = {"builds": []}
    for nx, ny, nt in SIZES:
        for mig in ("none", "stolt_fk_3d"):
            r = one(nx, ny, nt, mig)
            print(r, flush=True)
            res["builds"].append(r)
    if args.http:
        res["http"] = http_measure(args.http, args.dataset, args.volume, args.email, args.password)
        print(res["http"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
