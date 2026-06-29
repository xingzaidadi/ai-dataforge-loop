#!/usr/bin/env python3
"""Run the existing engine.py without changing the core data-making engine."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from common import ROOT, StepResult, parse_kv_pairs, write_json


def parse_business_data(output: str, params: dict[str, Any]) -> dict[str, Any]:
    """Extract user-facing business data from engine output."""
    patterns = {
        "prNo": [
            r"PR号[:：]\s*([A-Za-z0-9_-]+)",
            r"purchase_no['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_-]+)",
        ],
        "poNo": [
            r"PO号[:：]\s*([A-Za-z0-9_-]+)",
            r"purchase_order_no['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_-]+)",
        ],
        "erpNo": [
            r"ERP单号[:：]\s*([A-Za-z0-9_-]+)",
            r"erp_no['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_-]+)",
            r"erp_purchase_order_no['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_-]+)",
        ],
    }
    business_data: dict[str, Any] = {
        "orderType": params.get("orderType"),
        "stockOrg": params.get("stockOrg"),
        "purchaseOrg": params.get("purchaseOrg"),
        "supplierCode": params.get("supplierCode"),
        "materials": params.get("materials"),
        "projectCode": params.get("projectCode"),
        "shipLocCode": params.get("shipLocCode"),
    }
    for field, field_patterns in patterns.items():
        for pattern in field_patterns:
            match = re.search(pattern, output, flags=re.IGNORECASE)
            if match:
                business_data[field] = match.group(1)
                break
    return {key: value for key, value in business_data.items() if value not in (None, "", [], {})}


def run_datamake(config: str, params: dict[str, Any], run_dir: Path, dry_run: bool = False) -> StepResult:
    command = [sys.executable, str(ROOT / "engine.py"), config]
    for key, value in params.items():
        command.extend([f"--{key}", value if isinstance(value, str) else __import__("json").dumps(value, ensure_ascii=False)])

    if dry_run:
        result = StepResult(
            name="datamake",
            status="SKIPPED",
            detail="dry-run 模式未真实调用造数引擎",
            data={"command": command, "businessData": parse_business_data("", params)},
        )
        write_json(run_dir / "datamake-result.json", result.to_dict())
        return result

    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=480,  # 8 分钟超时，与 SKILL.md 性能预期一致
        )
        result = StepResult(
            name="datamake",
            status="SUCCESS" if completed.returncode == 0 else "FAILED",
            detail="造数引擎执行完成" if completed.returncode == 0 else "造数引擎执行失败",
            data={
                "returncode": completed.returncode,
                "command": command,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "businessData": parse_business_data(completed.stdout + "\n" + completed.stderr, params),
            },
        )
    except subprocess.TimeoutExpired:
        result = StepResult(
            name="datamake",
            status="FAILED",
            detail="造数引擎执行超时（8 分钟上限）",
            data={"command": command, "timeout": 480},
        )
    write_json(run_dir / "datamake-result.json", result.to_dict())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="调用现有 engine.py 执行造数")
    parser.add_argument("--config", required=True, help="configs 下的流程配置，如 configs/znb-prpo.yaml")
    parser.add_argument("--run-dir", required=True, help="证据目录")
    parser.add_argument("--dry-run", action="store_true", help="只生成命令，不真实执行")
    parser.add_argument("params", nargs="*", help="key=value 参数")
    args = parser.parse_args()

    result = run_datamake(args.config, parse_kv_pairs(args.params), Path(args.run_dir), args.dry_run)
    return 0 if result.status in {"SUCCESS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
