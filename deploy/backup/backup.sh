#!/usr/bin/env bash
set -euo pipefail
umask 077

fail() {
    printf '%s 备份失败：%s\n' "$(date -u +%FT%TZ)" "$1" >&2
    exit 1
}

backup_dir=/backups
archive="$backup_dir/idphone_prod-$(date -u +%F).dump"
exec 9>"$backup_dir/.backup.lock"
flock -n 9 || fail '另一个备份正在运行'

if [[ ! -s "$archive" ]]; then
    # 清理上次被中断的临时文件。只有成功写完的归档才会改名为 .dump。
    rm -f -- "$backup_dir"/.idphone_prod-*
    temp=$(mktemp "$backup_dir/.idphone_prod-XXXXXXXX")
    trap 'rm -f -- "$temp"' EXIT
    pg_dump --format=custom --no-password --file="$temp" >/dev/null 2>&1 ||
        fail 'pg_dump 未完成'
    pg_restore --list "$temp" >/dev/null 2>&1 || fail '归档目录无法读取'
    mv -- "$temp" "$archive"
    printf '%s 本地备份完成 %s\n' "$(date -u +%FT%TZ)" "${archive##*/}"
fi

find "$backup_dir" -maxdepth 1 -type f -name 'idphone_prod-????-??-??.dump' -mtime +13 -delete

if [[ -n "${BACKUP_OSS_URI:-}" ]]; then
    oss_dir=/run/backup-oss
    [[ "$BACKUP_OSS_URI" == oss://?* && -x "$oss_dir/ossutil" && -r "$oss_dir/.ossutilconfig" ]] ||
        fail '请检查 OSS 目标、ossutil 和挂载配置'
    "$oss_dir/ossutil" --config-file "$oss_dir/.ossutilconfig" cp \
        "$archive" "${BACKUP_OSS_URI%/}/${archive##*/}" --force >/dev/null 2>&1 ||
        fail 'OSS 上传未完成，本地归档已保留'
    printf '%s OSS 上传完成 %s\n' "$(date -u +%FT%TZ)" "${archive##*/}"
fi
