# MLflow tracking server image: official MLflow image + PostgreSQL driver.
# The official image is multi-arch (linux/amd64 and linux/arm64), so it runs
# natively on both Apple Silicon and Intel Macs.
ARG MLFLOW_VERSION=3.17.2
FROM ghcr.io/mlflow/mlflow:v${MLFLOW_VERSION}

# The official image does not ship a Postgres driver.
RUN pip install --no-cache-dir psycopg2-binary==2.9.13

EXPOSE 5000
