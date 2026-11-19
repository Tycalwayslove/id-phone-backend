"""导出 OpenAPI 接口文档。

用法（在 backend 目录下）：
    uv run python -m scripts.export_openapi            # 写到 openapi.json
    uv run python -m scripts.export_openapi out.json   # 写到指定路径

只读取代码里的接口定义，不连接数据库。
"""

import json
import sys
from pathlib import Path

from app.main import app


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    spec = app.openapi()
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写出 {out}（{len(spec.get('paths', {}))} 个路径）")


if __name__ == "__main__":
    main()
