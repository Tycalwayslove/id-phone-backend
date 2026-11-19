# 被 db_backup.sh / db_restore.sh 引用，不单独运行。
# 读出 DATABASE_URL，找到 pg_dump / pg_restore。

URL="${DATABASE_URL:-$(grep -E '^DATABASE_URL=' .env | cut -d= -f2-)}"
if [ -z "$URL" ]; then
  echo "找不到 DATABASE_URL：请在 backend/.env 里设置，或作为环境变量传入" >&2
  exit 1
fi
# SQLAlchemy 的写法 postgresql+psycopg:// 换成 PostgreSQL 工具认识的 postgresql://
URL="${URL/postgresql+psycopg:/postgresql:}"

# 只用于显示：主机、端口和库名，不显示密码
TARGET="${URL##*@}"
DB_NAME="${TARGET##*/}"
DB_NAME="${DB_NAME%%\?*}"

# 优先用 Postgres.app 自带的工具，版本和本机数据库一致
PG_APP_BIN="/Applications/Postgres.app/Contents/Versions/latest/bin"
pg_tool() {
  if [ -x "$PG_APP_BIN/$1" ]; then echo "$PG_APP_BIN/$1"; else command -v "$1"; fi
}
