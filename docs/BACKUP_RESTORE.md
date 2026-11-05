# Backup and restore

Two things hold state: the PostgreSQL volume (`growos_pgdata`) and the artifacts volume (`growos_artifacts`, raw payloads).
`.env` holds the secrets — without `APP_SECRET_KEY` the stored provider credentials cannot be decrypted. Back up all three.

## Backup

```bash
cd /path/to/growos
mkdir -p backups && TS=$(date +%Y%m%d-%H%M%S)
# database (logical dump, compressed)
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-growos}" -d "${POSTGRES_DB:-growos}" -Fc > backups/db-$TS.dump
# artifacts volume
docker run --rm -v growos_artifacts:/data:ro -v "$PWD/backups":/backup alpine tar czf /backup/artifacts-$TS.tgz -C /data .
# secrets
cp .env backups/env-$TS   # store securely (contains the encryption key)
```

Schedule it with cron, e.g. daily at 03:00: `0 3 * * * cd /path/to/growos && ./scripts/backup.sh` (adapt the lines above).

## Restore

```bash
docker compose down
docker volume rm growos_pgdata growos_artifacts   # only if you want a clean restore
docker compose up -d db
docker compose exec -T db pg_restore -U growos -d growos --clean --if-exists < backups/db-YYYYMMDD-HHMMSS.dump
docker run --rm -v growos_artifacts:/data -v "$PWD/backups":/backup alpine sh -c "cd /data && tar xzf /backup/artifacts-YYYYMMDD-HHMMSS.tgz"
cp backups/env-YYYYMMDD-HHMMSS .env
docker compose up -d
```

`pg_restore --clean` needs an existing database; the `db` service creates it on first start. Keep the same `APP_SECRET_KEY`.

## Upgrades

`docker compose pull && docker compose up -d --build` — the `migrate` service applies Alembic migrations before api/worker start.
Take a database backup first.
