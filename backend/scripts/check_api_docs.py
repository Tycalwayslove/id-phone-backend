"""检查接口文档有没有写全，缺了就列出来并以非零状态退出（CI 会因此失败）。

要求：
- 每个接口：tags、operation_id、summary、description、成功返回的 response_description
- 每个路径参数、查询参数、请求头参数：description
- 每个数据模型：类的 docstring；每个字段：description

用法（在 backend 目录下）：uv run python -m scripts.check_api_docs
"""

import sys

from app.main import app

# FastAPI 自带的模型，不归我们写
BUILTIN_SCHEMAS = {"HTTPValidationError", "ValidationError"}
DEFAULT_DESCRIPTIONS = {"Successful Response"}


def find_problems(spec: dict) -> list[str]:
    problems: list[str] = []

    for path, operations in spec.get("paths", {}).items():
        for method, op in operations.items():
            where = f"{method.upper()} {path}"
            if not op.get("tags"):
                problems.append(f"{where}：缺少 tags")
            op_id = op.get("operationId", "")
            if not op_id or op_id.startswith("MISSING_OPERATION_ID__"):
                problems.append(f"{where}：缺少 operation_id")
            for key in ("summary", "description"):
                if not op.get(key):
                    problems.append(f"{where}：缺少 {key}")
            for param in op.get("parameters", []):
                if not param.get("description"):
                    problems.append(f"{where}：参数 {param.get('name')} 缺少 description")
            for status, resp in op.get("responses", {}).items():
                if status == "422":
                    continue
                desc = resp.get("description", "")
                if not desc or desc in DEFAULT_DESCRIPTIONS:
                    problems.append(f"{where}：{status} 返回缺少说明（response_description 或 responses）")

    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        if name in BUILTIN_SCHEMAS:
            continue
        if not schema.get("description"):
            problems.append(f"模型 {name}：缺少类的 docstring")
        for field, prop in schema.get("properties", {}).items():
            if not prop.get("description"):
                problems.append(f"模型 {name}.{field}：缺少 description")

    return problems


def main() -> None:
    problems = find_problems(app.openapi())
    if problems:
        print(f"接口文档不完整，共 {len(problems)} 处：")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("接口文档检查通过")


if __name__ == "__main__":
    main()
