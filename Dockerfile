FROM python:3.12-slim

# GDAL/rasterio + segyio + laspy native deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev gdal-bin libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# setuptools>=81 dropped pkg_resources by default, which breaks older sdist
# builds (rasterio, some segyio/laspy versions) that still `import
# pkg_resources` in their build scripts. Pin it below that before anything else.
RUN pip install --no-cache-dir --upgrade pip "setuptools<81" wheel
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs datasets/{raw,processed,downloads,metadata,ground_truth,benchmarks}

EXPOSE 8000

CMD ["sh", "-c", "python docker/wait_for_db.py && uvicorn api.main:app --host 0.0.0.0 --port 8000"]
