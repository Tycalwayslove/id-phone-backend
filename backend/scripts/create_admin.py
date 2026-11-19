"""创建或更新后台账号。

运行（在 backend 目录下）：
    uv run python -m scripts.create_admin <username> <role>

role 取值：owner（所有者）、operator（运营）、finance（财务）。
密码交互输入两次（不回显），至少 10 位；账号已存在时更新密码和角色，并恢复为启用状态。
密码不会出现在命令行参数、日志或 shell 历史里。
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import AdminUser
from app.models.ops import ADMIN_ROLES

MIN_PASSWORD_LEN = 10


def main() -> None:
    parser = argparse.ArgumentParser(description="创建或更新后台账号")
    parser.add_argument("username", help="用户名，如 ops_zhang")
    parser.add_argument("role", choices=ADMIN_ROLES, help="角色")
    args = parser.parse_args()

    username = args.username.strip()
    if not username:
        sys.exit("用户名不能为空")

    password = getpass.getpass("密码：")
    if len(password) < MIN_PASSWORD_LEN:
        sys.exit(f"密码至少 {MIN_PASSWORD_LEN} 位")
    if getpass.getpass("再输入一次密码：") != password:
        sys.exit("两次输入的密码不一致")

    with SessionLocal() as db:
        admin = db.scalar(select(AdminUser).where(AdminUser.username == username))
        if admin is None:
            db.add(AdminUser(username=username, password_hash=hash_password(password), role=args.role))
            action = "已创建"
        else:
            admin.password_hash = hash_password(password)
            admin.role = args.role
            admin.status = "active"
            action = "已更新"
        db.commit()
    print(f"{action}后台账号 {username}（{args.role}）")


if __name__ == "__main__":
    main()
