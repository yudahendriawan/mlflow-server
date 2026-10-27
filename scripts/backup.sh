#!/usr/bin/env bash
# Back up the MLflow PostgreSQL database and the artifacts volume into backups/<timestamp>/.
#
# Output files:
#   db.dump            pg_dump in custom format (restore with pg_restore)
#   artifacts.tar.gz   contents of the mlartifacts volume
#   MLFLOW_VERSION     MLflow version the backup was taken with
set -euo pipefail

cd "$(dirname "$0")/.."

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -f .env ]] || die ".env not found in $(pwd). Create it from .env.example first."
set -a
# shellcheck disable=SC1091
source .env
set +a

docker compose ps --status running --services | grep -qx postgres \
  || die "The postgres service is not running. Start the stack with 'make up' first."

backup_dir="backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
# Remove a half-written backup directory if anything below fails.
completed=false
trap '[[ "$completed" == true ]] || { echo "Backup failed, removing $backup_dir" >&2; rm -rf "$backup_dir"; }' EXIT

echo "==> Dumping database '$POSTGRES_DB' to $backup_dir/db.dump"
docker compose exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom > "$backup_dir/db.dump"

echo "==> Archiving artifacts volume to $backup_dir/artifacts.tar.gz"
docker compose run --rm --no-deps -T --entrypoint tar mlflow \
  -czf - -C /mlartifacts . > "$backup_dir/artifacts.tar.gz"

echo "$MLFLOW_VERSION" > "$backup_dir/MLFLOW_VERSION"

[[ -s "$backup_dir/db.dump" ]] || die "Database dump is empty."
tar -tzf "$backup_dir/artifacts.tar.gz" > /dev/null || die "Artifacts archive is corrupt."

completed=true
echo "==> Backup complete: $backup_dir"
du -sh "$backup_dir"/*
