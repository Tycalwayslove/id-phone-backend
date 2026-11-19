#!/usr/bin/env bash
# 把 DATABASE_URL 指向的数据库备份成一个文件，放在 backend/backups/（不进 git）。
# 用法（在 backend 目录下）：./scripts/db_backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_pg_env.sh

PG_DUMP="$(pg_tool pg_dump)"
mkdir -p backups
OUT="backups/${DB_NAME}_$(date +%Y%m%d_%H%M%S).dump"

echo "正在备份 $TARGET ..."
"$PG_DUMP" --format=custom --no-owner --no-privileges --dbname="$URL" --file="$OUT"
echo "已备份到 $OUT（$(du -h "$OUT" | cut -f1)）"
