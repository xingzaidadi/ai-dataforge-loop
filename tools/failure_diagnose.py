#!/usr/bin/env python3
"""Diagnose failed data-making or UI verification with logs and screenshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import StepResult, read_json, write_json


RULES = [
    ("缺少 UI 验收入口", "配置缺失", "补充 configs/ui-verify-prpo.yaml 的 base_url，或设置 SCM_BASE_URL。"),
    ("未安装 playwright", "环境依赖缺失", "执行 pip install playwright && python -m playwright install chromium。"),
    ("Timeout", "页面等待超时", "检查查询条件、页面加载速度、选择器是否变化。"),
    ("not found", "页面元素或业务数据未找到", "核对单号是否生成成功，确认 UI 查询条件和状态流转是否一致。"),
    ("Cookie 获取失败", "登录态失效", "刷新 Cookie 获取接口或重新配置登录态。"),
    ("造数引擎执行失败", "造数主流程失败", "查看 datamake-result.json 的 stderr/stdout，优先处理首个失败 Action。"),
]


def _collect_json(run_dir: Path, file_name: str) -> dict[str, Any]:
    path = run_dir / file_name
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except json.JSONDecodeError:
        return {"error": f"{file_name} 不是合法 JSON"}


def _find_failed_screenshots(run_dir: Path) -> list[str]:
    return [str(path) for path in sorted((run_dir / "screenshots").glob("failed-*.png"))]


def diagnose_failure(run_dir: Path, screenshot: str | None = None) -> StepResult:
    datamake = _collect_json(run_dir, "datamake-result.json")
    ui_verify = _collect_json(run_dir, "ui-verify-result.json")
    haystack = json.dumps({"datamake": datamake, "uiVerify": ui_verify}, ensure_ascii=False)

    suggestions = []
    for keyword, category, action in RULES:
        if keyword.lower() in haystack.lower():
            suggestions.append({"category": category, "evidence": keyword, "action": action})

    screenshots = _find_failed_screenshots(run_dir)
    if screenshot:
        screenshots.insert(0, screenshot)
    if screenshots and not suggestions:
        suggestions.append({
            "category": "失败截图待人工确认",
            "evidence": screenshots[0],
            "action": "打开失败截图，对照页面提示、查询条件和生成单号，确认是页面选择器变化还是数据未流转。",
        })

    if not suggestions:
        suggestions.append({
            "category": "未命中规则",
            "evidence": "未发现已知错误模式",
            "action": "查看 summary.json、datamake-result.json、ui-verify-result.json，并补充新的诊断规则。",
        })

    result = StepResult(
        name="failure_diagnose",
        status="SUCCESS",
        detail="已生成失败诊断建议",
        data={"suggestions": suggestions, "failedScreenshots": screenshots[:5]},
    )
    write_json(run_dir / "diagnosis.json", result.to_dict())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="基于日志和截图生成失败诊断")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--screenshot")
    args = parser.parse_args()

    diagnose_failure(Path(args.run_dir), args.screenshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
