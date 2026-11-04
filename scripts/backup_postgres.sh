#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backup_dir="${1:-$repo_dir/backups}"
if [[ ! -f "$repo_dir/.env.prod" ]]; then
  echo "Missing $repo_dir/.env.prod" >&2
  exit 1
fi
umask 077
mkdir -p "$backup_dir"
target="$backup_dir/headcount-$(date -u +%Y%m%dT%H%M%SZ).dump"
if [[ -e "$target" ]]; then
  echo "Backup already exists: $target" >&2
  exit 1
fi
temporary="$(mktemp "$backup_dir/.headcount-backup.XXXXXXXX")"
trap 'rm -f "$temporary"' EXIT
cd "$repo_dir"
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T postgres \
  sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$temporary"
chmod 600 "$temporary"
ln "$temporary" "$target"
echo "$target"
