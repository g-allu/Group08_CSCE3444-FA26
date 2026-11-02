# Container for the combined Flask frontend and ASL inference API (used by Render).
FROM python:3.12-slim

# MediaPipe and OpenCV wheels need these shared libraries.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
COPY backend/requirements.txt backend/
COPY ml/requirements.txt ml/
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0

COPY . .

ENV MPLCONFIGDIR=/tmp/matplotlib \
    PYTHONUNBUFFERED=1

# One worker: each process loads its own MediaPipe detector; ModelService serializes predictions.
CMD gunicorn --workers 1 --threads 2 --timeout 120 --bind 0.0.0.0:${PORT:-10000} "backend.app:create_app()"
