FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install .

COPY data ./data
# Bake the database into the image: the API only reads it, so every container
# starts with identical data and no startup work.
ENV CIRCLES_DATA_DIR=/srv/data \
    CIRCLES_DATABASE_PATH=/srv/var/circles.db \
    CIRCLES_AUTO_SEED=false \
    CIRCLES_LOG_JSON=true
RUN python -m app.db.seed

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
