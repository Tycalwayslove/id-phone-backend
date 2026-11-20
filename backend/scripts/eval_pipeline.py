"""用授权照片对比不同档位。默认只读取规格并在本机生成报告。

在 backend 目录运行：
    uv run python -m scripts.eval_pipeline --input eval/input --spec gd_idcard --beauty 0,2,4 --matting both
    uv run python -m scripts.eval_pipeline --spec gd_idcard --check
只有同时传入 --check 和 --yes 才会把成品发送给鹧应检测。
"""

import argparse
import base64
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from html import escape
from pathlib import Path

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import engine
from app.integrations.matting import FineMatting, LocalMatting
from app.models import Provider, ProviderSpec, Spec
from app.modules.photos import imaging
from app.modules.photos.pipeline.face import detect_faces
from app.modules.photos.pipeline.quality import assess_quality

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
CHECK_PRICE = Decimal("0.012")
MATTING_LABELS = {"fast": "MODNet 快速抠图", "fine": "BiRefNet 精细抠图"}
type VariantKey = tuple[str, str, int]


@dataclass(frozen=True)
class CheckResult:
    title: str
    passed: bool | None = None
    passed_list: tuple[dict, ...] = ()

    def to_html(self) -> str:
        title = escape(self.title)
        if not self.passed_list:
            return title
        items = []
        for item in self.passed_list:
            key = escape(str(item.get("key", "")))
            msg = escape(str(item.get("msg", "") or ""))
            match item.get("passed"):
                case 1 | "1":
                    status = "通过"
                case 0 | "0":
                    status = "未通过"
                case _:
                    status = "未知"
            # 保留服务商返回的原始明细结构，包括实测值、单位和附加字段。
            detail = {k: v for k, v in item.items() if k not in ("key", "passed", "msg")}
            measurement = escape(json.dumps(detail, ensure_ascii=False)) if detail else "—"
            items.append(
                f"<li><code>{key}</code> · {status} {msg}<br>实测明细 <code>{measurement}</code></li>"
            )
        return f"{title}<ul>{''.join(items)}</ul>"


def _beauty_levels(value: str) -> list[int]:
    try:
        levels = sorted({int(level) for level in value.split(",")})
    except ValueError:
        levels = []
    if not levels or not all(0 <= level <= 5 for level in levels):
        raise argparse.ArgumentTypeError("请输入 0～5 的整数档位，以逗号分隔，例如 0,2,4")
    return levels


def _load_specs(codes: list[str], *, with_mapping: bool) -> tuple[list[Spec], dict[str, str]]:
    with Session(engine) as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        rows = {spec.code: spec for spec in db.scalars(select(Spec).where(Spec.code.in_(codes)))}
        missing = set(codes) - rows.keys()
        if missing:
            raise ValueError("找不到这些规格：" + "、".join(sorted(missing)))
        items = {}
        if with_mapping:
            stmt = (
                select(Spec.code, ProviderSpec.provider_item_id)
                .join(ProviderSpec, ProviderSpec.spec_id == Spec.id)
                .join(Provider, Provider.id == ProviderSpec.provider_id)
                .where(Spec.code.in_(codes), Provider.adapter == "zheying", Provider.status == "enabled")
                .where(ProviderSpec.is_enabled.is_(True), ProviderSpec.provider_item_id != "")
                .order_by(Provider.id)
            )
            for code, item_id in db.execute(stmt):
                items.setdefault(code, item_id)
        return [rows[code] for code in codes], items


def _inputs(folder: Path) -> list[tuple[Path, str]]:
    if not folder.is_dir():
        raise ValueError(f"输入目录不存在：{folder}")
    inputs = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        try:
            fmt, _, _ = imaging.inspect_image(path.read_bytes())
        except imaging.ImageInvalidError as exc:
            print(f"跳过 {path.name}：{exc}")
        else:
            inputs.append((path, imaging.ALLOWED_FORMATS[fmt][1]))
    if not inputs:
        raise ValueError(f"没有可处理的 JPEG 或 PNG：{folder}")
    return inputs


def _check(client: httpx.Client, data: bytes, item_id: str) -> CheckResult:
    try:
        response = client.post(
            f"{settings.zheying_api_base.rstrip('/')}/idphoto/check",
            data={
                "key": settings.zheying_app_key,
                "image": base64.b64encode(data).decode("ascii"),
                "item_id": item_id,
            },
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        return CheckResult(f"检测请求失败（HTTP {exc.response.status_code}）")
    except httpx.RequestError, ValueError:
        return CheckResult("检测请求失败或响应无法解析")

    if not isinstance(payload, dict):
        return CheckResult("检测响应格式无效")
    if payload.get("code") != 0:
        return CheckResult(f"检测接口返回错误（{payload.get('code', '未知')}）")
    result = payload.get("data")
    if not isinstance(result, dict):
        return CheckResult("检测响应缺少有效结果")
    checks = result.get("passed_list")
    passed_list = tuple(item for item in checks if isinstance(item, dict)) if isinstance(checks, list) else ()
    if result.get("passed_status") not in (0, 1):
        return CheckResult("检测响应缺少有效结果", passed_list=passed_list)
    passed = result["passed_status"] == 1
    return CheckResult("通过" if passed else "未通过", passed, passed_list)


def _tile(path: str, label: str, result: CheckResult | None = None) -> str:
    detail = f"<div>{result.to_html()}</div>" if result is not None else ""
    return (
        f'<figure><a href="{path}"><img loading="lazy" src="{path}" alt="{escape(label)}"></a>'
        f"<figcaption>{escape(label)}{detail}</figcaption></figure>"
    )


def _write_report(
    output: Path,
    sections: list[str],
    totals: Counter[VariantKey],
    passes: Counter[VariantKey],
    covered_checks: set[str],
    notice: str,
) -> None:
    summary = "".join(
        f"<li>{escape(code)} · {MATTING_LABELS[mode]} · 档位 {level} · {passes[mode, code, level]}/{total} "
        f"（{passes[mode, code, level] / total:.1%}）</li>"
        for (mode, code, level), total in totals.items()
    )
    summary_section = f"<h2>过检率</h2><ul>{summary}</ul>" if summary else ""
    checked_items = "、".join(f"<code>{escape(key)}</code>" for key in sorted(covered_checks))
    coverage = f"<h2>本次检测覆盖的检查项</h2><p>{checked_items or '无检测明细'}</p>"
    (output / "report.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>照片处理评估</title><style>"
        "body{font:16px/1.5 system-ui,sans-serif;margin:2rem;color:#262626;background:#fafafa}"
        "section{margin-block:2rem;padding-block-start:.5rem;border-top:1px solid #ccc}"
        ".images{display:flex;gap:1rem;overflow:auto;padding-bottom:.5rem}"
        "figure{flex:0 0 180px;margin:0}img{width:180px;height:220px;object-fit:contain;"
        "background:repeating-conic-gradient(#ddd 0% 25%,white 0% 50%) 0 0/16px 16px}"
        "figcaption ul{padding-inline-start:1.2rem;overflow-wrap:anywhere}"
        "</style><main><h1>照片处理评估</h1>"
        f"<p>{escape(notice)}</p>{coverage}{summary_section}{''.join(sections)}</main></html>",
        encoding="utf-8",
    )


def _evaluate(
    inputs: list[tuple[Path, str]],
    variants: list[tuple[Spec, int]],
    items: dict[str, str],
    client: httpx.Client | None,
    notice: str,
    modes: tuple[str, ...],
) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
    output = EVAL_DIR / "output" / timestamp
    output.mkdir(parents=True, mode=0o700)
    models = {"fast": LocalMatting(), "fine": FineMatting()}
    sections = []
    totals: Counter[VariantKey] = Counter()
    passes: Counter[VariantKey] = Counter()
    covered_checks: set[str] = set()
    for index, (path, ext) in enumerate(inputs, start=1):
        folder = output / f"{index:03d}"
        folder.mkdir()
        original_name = f"original.{ext}"
        shutil.copyfile(path, folder / original_name)
        original = (folder / original_name).read_bytes()
        with imaging.decode_photo(original) as image:
            faces = detect_faces(image)
            quality = assess_quality(image, faces)
        face = faces[0] if faces else None
        tiles = [_tile(f"{folder.name}/{original_name}", "原图")]
        for mode in modes:
            label = MATTING_LABELS[mode]
            suffix = "-fine" if mode == "fine" else ""
            matte = models[mode].matte(original)
            matting_name = f"matting{suffix}.png"
            (folder / matting_name).write_bytes(matte)
            tiles.append(_tile(f"{folder.name}/{matting_name}", label))
            for variant_index, (spec, level) in enumerate(variants, start=1):
                data = imaging.make_render(
                    matte,
                    width_px=spec.width_px,
                    height_px=spec.height_px,
                    bg_color=(spec.bg_colors or ["#FFFFFF"])[0],
                    dpi=spec.dpi,
                    max_kb=spec.file_size_max_kb,
                    watermarked=False,
                    beauty_level=level,
                    face=face,
                )
                name = f"render{suffix}-{variant_index:03d}.jpg"
                (folder / name).write_bytes(data)
                result = None
                if client is not None and spec.code in items:
                    result = _check(client, data, items[spec.code])
                    covered_checks.update(str(item["key"]) for item in result.passed_list if item.get("key"))
                    if result.passed is not None:
                        totals[mode, spec.code, level] += 1
                        passes[mode, spec.code, level] += result.passed
                tiles.append(_tile(f"{folder.name}/{name}", f"{label} · {spec.code} · 档位 {level}", result))
        hints = "；".join(issue.message for issue in quality.issues)
        level_label = {"ok": "合格", "warn": "有建议", "fail": "建议重拍"}[quality.level]
        sections.append(
            f"<section><h2>{escape(path.name)}</h2>"
            f"<p>拍后检测 · {level_label} {escape(hints)}</p>"
            f'<div class="images">{"".join(tiles)}</div></section>'
        )
    _write_report(output, sections, totals, passes, covered_checks, notice)
    return output / "report.html"


def main() -> None:
    parser = argparse.ArgumentParser(description="生成照片处理对照报告，可选鹧应付费检测。")
    parser.add_argument("--input", type=Path, default=EVAL_DIR / "input", help="待评估 JPEG / PNG 的目录")
    parser.add_argument("--spec", nargs="+", action="extend", required=True, help="规格编码，可传多个")
    parser.add_argument("--beauty", type=_beauty_levels, default="0,2,4", help="以逗号分隔的美颜档位")
    parser.add_argument("--matting", choices=("fast", "fine", "both"), default="fast", help="选择抠图模型")
    parser.add_argument("--check", action="store_true", help="预估鹧应检测次数和费用")
    parser.add_argument("--yes", action="store_true", help="与 --check 一起使用，确认发起付费检测")
    args = parser.parse_args()

    try:
        inputs = _inputs(args.input)
        specs, items = _load_specs(list(dict.fromkeys(args.spec)), with_mapping=args.check)
        variants = [(spec, level) for spec in specs for level in args.beauty if level <= spec.beauty_max]
        if not variants:
            raise ValueError("没有可用档位，请选择规格允许的美颜档位")
        skipped = [
            f"{spec.code} 档位 {level}" for spec in specs for level in args.beauty if level > spec.beauty_max
        ]
        notice = f"已跳过超过规格上限的档位：{'、'.join(skipped)}。" if skipped else ""
        modes = ("fast", "fine") if args.matting == "both" else (args.matting,)
        count = len(inputs) * len(modes) * sum(spec.code in items for spec, _ in variants)
        if args.check:
            print(f"将调用 {count} 次，预计 {count * CHECK_PRICE:.3f} 元", flush=True)
            unmapped = sorted({spec.code for spec, _ in variants if spec.code not in items})
            if unmapped:
                notice += f"以下规格缺少可用的鹧应映射：{'、'.join(unmapped)}。"
        if args.check and args.yes and count:
            if not settings.zheying_app_key:
                raise ValueError("请配置 ZHEYING_APP_KEY")
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                report = _evaluate(inputs, variants, items, client, notice + "已启用鹧应检测。", modes)
        else:
            if args.check and not args.yes:
                print("本次仅预估费用。增加 --yes 后才会发起检测。")
            report = _evaluate(inputs, variants, items, None, notice + "本次未发起付费检测。", modes)
    except (ValueError, FileNotFoundError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"报告已生成：{report}")


if __name__ == "__main__":
    main()
