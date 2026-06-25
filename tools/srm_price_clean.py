#!/usr/bin/env python3
"""SRM 寻源价格造数 — PRPO 前置数据清洗执行器。

用法：
    python tools/srm_price_clean.py --config configs/srm-price-clean.yaml --参数
    python tools/srm_price_clean.py --config configs/srm-price-clean.yaml --dry-run --参数

在闭环流程中由 closed_loop_runner.py 调用，不直接运行。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

from common import ROOT, StepResult, parse_kv_pairs, write_json


def run_srm_price_clean(
    config: str,
    params: dict[str, Any],
    run_dir: Path,
    dry_run: bool = False,
) -> StepResult:
    """执行 SRM 寻源价格清洗。

    返回 StepResult，status 为 SUCCESS / FAILED / SKIPPED。
    """
    command = [sys.executable, str(ROOT / "engine.py"), config]
    for key, value in params.items():
        command.extend([
            f"--{key}",
            value if isinstance(value, str) else __import__("json").dumps(value, ensure_ascii=False),
        ])

    if dry_run:
        result = StepResult(
            name="srm_price_clean",
            status="SKIPPED",
            detail="dry-run 模式未真实执行 SRM 价格清洗",
            data={"command": command},
        )
        write_json(run_dir / "srm-price-clean-result.json", result.to_dict())
        return result

    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    result = StepResult(
        name="srm_price_clean",
        status="SUCCESS" if completed.returncode == 0 else "FAILED",
        detail="SRM 价格清洗完成" if completed.returncode == 0 else "SRM 价格清洗失败",
        data={
            "returncode": completed.returncode,
            "command": command,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        },
    )
    write_json(run_dir / "srm-price-clean-result.json", result.to_dict())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="SRM 寻源价格清洗（独立运行）")
    parser.add_argument("--config", default="configs/srm-price-clean.yaml", help="清洗配置")
    parser.add_argument("--run-dir", default=".", help="输出目录")
    parser.add_argument("--dry-run", action="store_true", help="只生成命令不执行")
    parser.add_argument("params", nargs="*", help="key=value 参数")
    args = parser.parse_args()

    result = run_srm_price_clean(
        config=args.config,
        params=parse_kv_pairs(args.params),
        run_dir=Path(args.run_dir),
        dry_run=args.dry_run,
    )
    print(result.detail)
    return 0 if result.status in {"SUCCESS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
