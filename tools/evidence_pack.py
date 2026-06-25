#!/usr/bin/env python3
"""Build a lightweight HTML evidence pack for contest demo and daily tracing."""

from __future__ import annotations

import argparse
import html
from pathlib import Path

from common import StepResult, read_json, write_json


def _safe_json(run_dir: Path, file_name: str) -> dict:
    path = run_dir / file_name
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def build_evidence_pack(run_dir: Path, title: str = "AI 数据智造多模态闭环证据包") -> StepResult:
    summary = _safe_json(run_dir, "summary.json")
    intent = _safe_json(run_dir, "intent.json")
    datamake = _safe_json(run_dir, "datamake-result.json")
    ui_verify = _safe_json(run_dir, "ui-verify-result.json")
    diagnosis = _safe_json(run_dir, "diagnosis.json")
    screenshots = sorted((run_dir / "screenshots").glob("*.png"))

    screenshot_html = "\n".join(
        f"<figure><img src='screenshots/{html.escape(path.name)}' /><figcaption>{html.escape(path.name)}</figcaption></figure>"
        for path in screenshots
    )

    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #1f2937; }}
    h1 {{ color: #111827; }}
    section {{ margin: 24px 0; padding: 16px; border: 1px solid #e5e7eb; border-radius: 12px; }}
    pre {{ white-space: pre-wrap; background: #f9fafb; padding: 12px; border-radius: 8px; overflow-x: auto; }}
    img {{ max-width: 100%; border: 1px solid #e5e7eb; border-radius: 8px; }}
    figure {{ margin: 16px 0; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <section><h2>执行摘要</h2><pre>{html.escape(__import__("json").dumps(summary, ensure_ascii=False, indent=2))}</pre></section>
  <section><h2>意图识别</h2><pre>{html.escape(__import__("json").dumps(intent, ensure_ascii=False, indent=2))}</pre></section>
  <section><h2>造数结果</h2><pre>{html.escape(__import__("json").dumps(datamake, ensure_ascii=False, indent=2))}</pre></section>
  <section><h2>UI 验收</h2><pre>{html.escape(__import__("json").dumps(ui_verify, ensure_ascii=False, indent=2))}</pre></section>
  <section><h2>失败诊断</h2><pre>{html.escape(__import__("json").dumps(diagnosis, ensure_ascii=False, indent=2))}</pre></section>
  <section><h2>截图证据</h2>{screenshot_html or "<p>暂无截图。</p>"}</section>
</body>
</html>
"""
    report_path = run_dir / "report.html"
    report_path.write_text(page, encoding="utf-8")
    result = StepResult(
        name="evidence_pack",
        status="SUCCESS",
        detail="HTML 证据包已生成",
        data={"report": str(report_path), "screenshots": [str(path) for path in screenshots]},
    )
    write_json(run_dir / "evidence-pack.json", result.to_dict())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 HTML 证据包")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--title", default="AI 数据智造多模态闭环证据包")
    args = parser.parse_args()

    build_evidence_pack(Path(args.run_dir), args.title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
