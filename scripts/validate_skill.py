#!/usr/bin/env python3
"""
静态校验 AI 数据智造闭环引擎 Skill。

校验内容:
- Python 配置可加载并展开 use 指令
- action 类型合法
- step id 不重复
- goto/then/else/default/switch case 指向存在的 step 或 terminal
- route 指向的子流程配置存在
- template 文件存在
- 仓库中不包含明显的真实 token / 内部地址 / 数据库密码模式

不执行真实 HTTP、SQL 或造单流程。
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.config import load_config  # noqa: E402


ALLOWED_ACTIONS = {
    "http_call",
    "sql_query",
    "template",
    "condition",
    "switch",
    "loop",
    "route",
    "sql_execute",
    "filter_collection",
    "noop",
}

SECRET_PATTERNS = {
    "real_mify_token": re.compile(r"app-[A-Za-z0-9]{16,}"),
    "real_mysql_uri": re.compile(r"mysql\+pymysql://[^$\s]+:[^$\s]+@"),
    "internal_mioffice_url": re.compile(r"https?://[^\s\"']*mioffice\.cn"),
    "internal_toolskit_url": re.compile(r"https?://[^\s\"']*toolskit\.test\.mi\.com"),
}


def walk_steps(steps: list[dict[str, Any]], out: list[dict[str, Any]]) -> None:
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        out.append(step)
        nested = step.get("steps")
        if isinstance(nested, list):
            walk_steps(nested, out)


def validate_config(path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        config = load_config(str(path))
    except Exception as exc:  # noqa: BLE001
        return [f"{path.name}: 配置加载失败: {exc}"], warnings

    steps: list[dict[str, Any]] = []
    walk_steps(config.get("steps", []), steps)

    ids = [step.get("id") for step in steps if step.get("id")]
    duplicates = [step_id for step_id, count in Counter(ids).items() if count > 1]
    if duplicates:
        errors.append(f"{path.name}: step id 重复: {duplicates}")

    terminals = set((config.get("terminals") or {}).keys())
    all_targets = set(ids) | terminals

    for step in steps:
        step_id = step.get("id", "<unknown>")
        action = step.get("action")
        if action and action not in ALLOWED_ACTIONS:
            errors.append(f"{path.name}:{step_id}: 未知 action: {action}")

        template = step.get("template")
        if template and not (ROOT / template).exists():
            errors.append(f"{path.name}:{step_id}: 模板不存在: {template}")

        for key in ("goto", "then", "else", "default", "goto_fail"):
            target = step.get(key)
            if isinstance(target, str) and target and target not in all_targets:
                errors.append(f"{path.name}:{step_id}: {key} 指向不存在目标: {target}")

        for case in step.get("cases", []) or []:
            if not isinstance(case, dict):
                continue
            target = case.get("goto")
            if isinstance(target, str) and target not in all_targets:
                errors.append(f"{path.name}:{step_id}: case.goto 指向不存在目标: {target}")

        if action == "route":
            for route_name, route_path in (step.get("routes") or {}).items():
                route_file = ROOT / route_path
                if not route_file.exists():
                    errors.append(
                        f"{path.name}:{step_id}: 路由 {route_name} 指向不存在配置: {route_path}"
                    )

        if action == "loop" and step.get("collect", "results") == "results":
            warnings.append(f"{path.name}:{step_id}: loop 使用默认 collect=results，建议改成语义化名称")

    return errors, warnings


def scan_secrets() -> list[str]:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.name == ".env.example":
            continue
        if path == Path(__file__).resolve():
            continue
        if path.suffix.lower() in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf"}:
            continue
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{rel}:{line}: 命中敏感模式 {name}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="静态校验 AI 数据智造闭环引擎 Skill")
    parser.add_argument("--strict", action="store_true", help="将 warning 也视为失败")
    args = parser.parse_args()

    config_files = sorted((ROOT / "configs").glob("*.yaml"))
    config_files = [p for p in config_files if p.name != "mify-endpoint.yaml"]

    all_errors: list[str] = []
    all_warnings: list[str] = []

    for path in config_files:
        errors, warnings = validate_config(path)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    secret_findings = scan_secrets()
    all_errors.extend(secret_findings)

    print(f"校验配置数: {len(config_files)}")

    if all_warnings:
        print("\nWarnings:")
        for item in all_warnings:
            print(f"  - {item}")

    if all_errors:
        print("\nErrors:")
        for item in all_errors:
            print(f"  - {item}")
        return 1

    if args.strict and all_warnings:
        return 1

    print("静态校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
