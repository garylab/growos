#!/usr/bin/env bash
# GrowOS backup: PostgreSQL dump + artifacts volume + .env (holds the encryption key).
# Usage:  ./scripts/backup.sh [backup_dir]   (default: ./backups).  Cron example:  0 3 * * * cd /path/to/growos && ./scripts/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="${1:-backups}"; TS="$(date +%Y%m%d-%H%M%S)"; KEEP="${BACKUP_KEEP:-14}"
mkdir -p "$DIR"
set -a; [ -f .env ] && . ./.env; set +a
PGUSER="${POSTGRES_USER:-growos}"; PGDB="${POSTGRES_DB:-growos}"

echo "[backup] database -> $DIR/db-$TS.dump"
docker compose exec -T db pg_dump -U "$PGUSER" -d "$PGDB" -Fc > "$DIR/db-$TS.dump"

echo "[backup] artifacts volume -> $DIR/artifacts-$TS.tgz"
docker run --rm -v growos_artifacts:/data:ro -v "$PWD/$DIR":/backup alpine \
  tar czf "/backup/artifacts-$TS.tgz" -C /data . 2>/dev/null || echo "[backup] artifacts volume empty or missing, skipped"

cp .env "$DIR/env-$TS" 2>/dev/null && chmod 600 "$DIR/env-$TS" || true

echo "[backup] pruning backups older than $KEEP days"
find "$DIR" -name 'db-*.dump' -mtime "+$KEEP" -delete 2>/dev/null || true
find "$DIR" -name 'artifacts-*.tgz' -mtime "+$KEEP" -delete 2>/dev/null || true
find "$DIR" -name 'env-*' -mtime "+$KEEP" -delete 2>/dev/null || true
echo "[backup] done: $(ls -1 "$DIR"/db-$TS.dump)"
