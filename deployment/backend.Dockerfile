FROM python:3.12-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/pipeline ./pipeline
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/data PORT=8080
RUN useradd --uid 10001 --create-home app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
WORKDIR /app
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY data/processed/perfumes.parquet data/processed/features.npz data/processed/vocab.json data/processed/scores.parquet data/processed/clones.parquet data/processed/images.json /data/processed/
USER 10001
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8080}\" --workers 1 --no-access-log"]
