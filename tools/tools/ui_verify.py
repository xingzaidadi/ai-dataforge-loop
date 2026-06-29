#!/usr/bin/env python3
"""Verify generated data in a browser and capture screenshots with Python Playwright."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import yaml

from common import StepResult, write_json


def _load_yaml(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"UI 验收配置不存在: {path}")
    return yaml.safe_load(target.read_text(encoding="utf-8")) or {}


def _substitute(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        output = value
        for key, item in context.items():
            output = output.replace("${" + key + "}", str(item))
        return output
    if isinstance(value, list):
        return [_substitute(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, context) for key, item in value.items()}
    return value


def verify_ui(
    run_dir: Path,
    config_path: str | None = None,
    context: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> StepResult:
    context = context or {}
    config = _substitute(_load_yaml(config_path), context)
    screenshots_dir = run_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    if dry_run or not config.get("enabled", True):
        placeholder = screenshots_dir / "ui-verify-dry-run.txt"
        placeholder.write_text("UI 验收 dry-run：未启动浏览器。", encoding="utf-8")
        result = StepResult(
            name="ui_verify",
            status="SKIPPED",
            detail="dry-run 或配置禁用，未执行 UI 验收",
            data={"config": config, "screenshots": [str(placeholder)]},
        )
        write_json(run_dir / "ui-verify-result.json", result.to_dict())
        return result

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        result = StepResult(
            name="ui_verify",
            status="FAILED",
            detail="未安装 playwright，请执行 pip install playwright && python -m playwright install chromium",
            data={"config": config},
        )
        write_json(run_dir / "ui-verify-result.json", result.to_dict())
        return result

    base_url = config.get("base_url") or os.getenv("SCM_BASE_URL")
    if not base_url:
        result = StepResult(
            name="ui_verify",
            status="FAILED",
            detail="缺少 UI 验收入口，请在配置 base_url 或设置 SCM_BASE_URL",
            data={"config": config},
        )
        write_json(run_dir / "ui-verify-result.json", result.to_dict())
        return result

    steps: list[dict[str, Any]] = []
    status = "SUCCESS"
    detail = "UI 验收通过"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=bool(config.get("headless", True)))
        page = browser.new_page(viewport=config.get("viewport", {"width": 1440, "height": 1000}))
        try:
            url = str(config.get("url", base_url))
            if url.startswith("/"):
                url = base_url.rstrip("/") + url
            page.goto(url, wait_until=config.get("wait_until", "networkidle"), timeout=int(config.get("timeout_ms", 30000)))
            first_shot = screenshots_dir / "step-1-open-page.png"
            page.screenshot(path=str(first_shot), full_page=True)
            steps.append({"index": 1, "desc": "打开验收页面", "status": "SUCCESS", "screenshot": str(first_shot)})

            for index, operation in enumerate(config.get("steps", []), start=2):
                op_type = operation.get("type")
                desc = operation.get("desc") or op_type or f"step-{index}"
                try:
                    if op_type == "fill":
                        page.fill(operation["selector"], str(operation.get("value", "")))
                    elif op_type == "click":
                        page.click(operation["selector"])
                    elif op_type == "press":
                        page.press(operation["selector"], operation.get("key", "Enter"))
                    elif op_type == "wait_for_selector":
                        page.wait_for_selector(operation["selector"], timeout=int(operation.get("timeout_ms", 10000)))
                    elif op_type == "wait":
                        time.sleep(float(operation.get("seconds", 1)))
                    elif op_type == "assert_text":
                        expected = str(operation["text"])
                        page.locator(operation.get("selector", "body")).filter(has_text=expected).first.wait_for(
                            timeout=int(operation.get("timeout_ms", 10000))
                        )
                    else:
                        raise ValueError(f"未知 UI 操作类型: {op_type}")
                    shot = screenshots_dir / f"step-{index}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    steps.append({"index": index, "desc": desc, "status": "SUCCESS", "screenshot": str(shot)})
                except (Exception, PlaywrightTimeoutError) as exc:  # noqa: BLE001
                    status = "FAILED"
                    detail = f"UI 验收失败: {desc}"
                    shot = screenshots_dir / f"failed-{index}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    steps.append({"index": index, "desc": desc, "status": "FAILED", "error": str(exc), "screenshot": str(shot)})
                    break
        finally:
            browser.close()

    result = StepResult(name="ui_verify", status=status, detail=detail, data={"config": config, "steps": steps})
    write_json(run_dir / "ui-verify-result.json", result.to_dict())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="执行 Python Playwright UI 验收")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--config")
    parser.add_argument("--context-json", default="{}")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = verify_ui(Path(args.run_dir), args.config, json.loads(args.context_json), args.dry_run)
    return 0 if result.status in {"SUCCESS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
