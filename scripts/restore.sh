#!/usr/bin/env bash
# Restore the MLflow PostgreSQL database and artifacts volume from a backup directory
# created by scripts/backup.sh. This REPLACES all current MLflow data.
#
# Usage: scripts/restore.sh backups/<timestamp>
set -euo pipefail

cd "$(dirname "$0")/.."

die() { echo "ERROR: $*" >&2; exit 1; }

[[ $# -eq 1 ]] || die "Usage: $0 backups/<timestamp>"
backup_dir="${1%/}"

[[ -d "$backup_dir" ]] || die "Backup directory '$backup_dir' does not exist."
[[ -s "$backup_dir/db.dump" ]] || die "'$backup_dir/db.dump' is missing or empty."
[[ -f "$backup_dir/artifacts.tar.gz" ]] || die "'$backup_dir/artifacts.tar.gz' is missing."
tar -tzf "$backup_dir/artifacts.tar.gz" > /dev/null || die "'$backup_dir/artifacts.tar.gz' is corrupt."

[[ -f .env ]] || die ".env not found in $(pwd). Create it from .env.example first."
set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ -f "$backup_dir/MLFLOW_VERSION" ]]; then
  backup_version="$(cat "$backup_dir/MLFLOW_VERSION")"
  if [[ "$backup_version" != "$MLFLOW_VERSION" ]]; then
    echo "WARNING: backup was taken with MLflow $backup_version, current MLFLOW_VERSION is $MLFLOW_VERSION."
    echo "         If the server fails to start afterwards, run 'make db-upgrade'."
  fi
fi

echo "This will DELETE all current MLflow data (database '$POSTGRES_DB' and all artifacts)"
echo "and replace it with the contents of '$backup_dir'."
read -r -p "Type 'yes' to continue: " answer
[[ "$answer" == "yes" ]] || die "Aborted by user. Nothing was changed."

echo "==> Stopping the MLflow server"
docker compose stop mlflow

echo "==> Ensuring postgres is running and healthy"
docker compose up -d --wait postgres

echo "==> Recreating database '$POSTGRES_DB'"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE);" \
  -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";"

echo "==> Restoring database from $backup_dir/db.dump"
docker compose exec -T postgres \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error < "$backup_dir/db.dump"

echo "==> Restoring artifacts from $backup_dir/artifacts.tar.gz"
docker compose run --rm --no-deps -T --entrypoint sh mlflow \
  -c 'find /mlartifacts -mindepth 1 -delete && tar -xzf - -C /mlartifacts' \
  < "$backup_dir/artifacts.tar.gz"

echo "==> Starting the MLflow server"
docker compose up -d --wait mlflow

echo "==> Restore complete from $backup_dir"
