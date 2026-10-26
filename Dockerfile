# DiamondIQ server: API + web app + video analysis, one container.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DIAMONDIQ_POSE_MODEL=/srv/models/pose_landmarker_heavy.task

# MediaPipe needs EGL/GLES/GL and glib at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libegl1 libgles2 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY pyproject.toml README.md ./
COPY diamondiq ./diamondiq
RUN pip install ".[video,postgres]" && python -m diamondiq.biomechanics.pose --download

# Data (SQLite database when no DATABASE_URL is set, uploaded videos) lives in /data,
# which should be a persistent volume/disk.
RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app /data
USER app
WORKDIR /data
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health')"
# One worker: background video jobs, the setup code and sign-in throttling live in-process.
CMD ["sh", "-c", "uvicorn diamondiq.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
