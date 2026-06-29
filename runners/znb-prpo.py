#!/usr/bin/env python3
"""Safe ZNB-PRPO runner.

This runner intentionally does not store real tokens, database passwords,
internal URLs, suppliers, materials, or project numbers. Runtime secrets must
come from environment variables used by configs/mify-endpoint.yaml.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="ZNB-PRPO 安全执行入口")
    parser.add_argument("--dry-run", action="store_true", help="只生成报告，不真实调用造数和 UI")
    parser.add_argument("--run-id", default="", help="可选：指定本次运行编号")
    parser.add_argument("--supplier-code", default="SUPPLIER_DEMO")
    parser.add_argument("--material-code", default="MAT_DEMO")
    parser.add_argument("--project-code", default="PROJECT_DEMO")
    parser.add_argument("--ship-loc-code", default="LOC_DEMO")
    args = parser.parse_args()

    command = [
        sys.executable,
        str(ROOT / "tools" / "closed_loop_runner.py"),
        "--text",
        "帮我造一条生态链 ZNB PRPO，造完做页面验收",
        "--config",
        "configs/znb-prpo.yaml",
        "--ui-config",
        "configs/ui-verify-prpo.yaml",
        "orderType=ZNB",
        "stockOrg=MI_IOT",
        "purchaseOrg=2120",
        f"supplierCode={args.supplier_code}",
        "materials=" + json.dumps({"materialCode1": args.material_code}, ensure_ascii=False),
        f"projectCode={args.project_code}",
        f"shipLocCode={args.ship_loc_code}",
    ]
    if args.dry_run:
        command.insert(2, "--dry-run")
    if args.run_id:
        command[2:2] = ["--run-id", args.run_id]

    completed = subprocess.run(command, cwd=str(ROOT), check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
