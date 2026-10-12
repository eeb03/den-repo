# gprMax simulation image (roadmap M1a: owned ground truth by simulation).
#
# Kept SEPARATE from the API image on purpose: gprMax pulls in Cython,
# h5py, numpy-stl and friends that the platform does not need, and a
# solver upgrade must never move the platform's own pinned numpy/scipy.
#
# Pinned to 4.0.0 (2026-09-14) rather than 4.0.1 (2026-10-03): the newer
# release was nine days old when this was written. Same API; revisit once
# it has aged.
#
# PyPI ships no linux/aarch64 wheel, so on Apple Silicon Docker this builds
# from the sdist -- hence the compiler and OpenMP runtime. On x86_64 the
# prebuilt manylinux wheel is used and the compiler is simply unused.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir "gprMax==4.0.0"

WORKDIR /app
ENV MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1
