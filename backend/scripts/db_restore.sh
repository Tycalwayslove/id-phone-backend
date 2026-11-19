#!/usr/bin/env bash
# 把备份文件恢复到 DATABASE_URL 指向的数据库。目标库要先建好，并且是空库。
# 用法（在 backend 目录下）：./scripts/db_restore.sh backups/xxx.dump
# 备份里包含 alembic 的版本记录，恢复后迁移进度和原库一致。
set -euo pipefail
cd "$(dirname "$0")/.."
FILE="${1:?用法：./scripts/db_restore.sh <备份文件>}"
source scripts/_pg_env.sh

PG_RESTORE="$(pg_tool pg_restore)"
echo "将把 $FILE 恢复到 $TARGET"
read -r -p "确认请输入目标库名 ${DB_NAME}：" ANSWER
if [ "$ANSWER" != "$DB_NAME" ]; then
  echo "已取消"
  exit 1
fi

# 单个事务：中途出错会整体回滚，不会留下一半的数据
"$PG_RESTORE" --no-owner --no-privileges --exit-on-error --single-transaction --dbname="$URL" "$FILE"
echo "恢复完成"
