#!/usr/bin/env python3
"""SRM 寻源价格造数 — PRPO 前置数据清洗执行器。

用法：
    python tools/srm_price_clean.py --config configs/srm-price-clean.yaml --参数
    python tools/srm_price_clean.py --config configs/srm-price-clean.yaml --dry-run --参数

在闭环流程中由 closed_loop_runner.py 调用，不直接运行。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# Windows 控制台默认 GBK，含 emoji 的 print 会抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

from common import ROOT, StepResult, parse_kv_pairs, write_json


# 清洗必填字段（PRPO 造数依赖这些前置数据）
_REQUIRED_FIELDS = [
    ("materialCode", "物料MPN"),
    ("purchaseOrg", "采购组织"),
    ("supplierCode", "供应商"),
]

_OPTIONAL_DEFAULTS = {
    "materialType": "material",
    "sourceType": "ZWW",
    "purchaseMode": "NORMAL",
    "gross": "10000",
    "kpein": "WPCS",
    "taxCode": "J2",
    "taxrt": "0.13",
    "priceType": "mav_fee,odm_owned_fee",
}


def _validate_inputs(params: dict[str, Any]) -> list[str]:
    """校验必填字段，返回错误列表（空 = 通过）。"""
    errors = []
    for field, label in _REQUIRED_FIELDS:
        val = params.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"缺少必填字段: {field} ({label})")
    # 检查数值字段是否合法
    for field in ("gross", "taxrt"):
        val = params.get(field)
        if val is not None and isinstance(val, str):
            try:
                float(val)
            except ValueError:
                errors.append(f"字段 {field} 必须是数字: {val}")
    return errors


def _fill_defaults(params: dict[str, Any]) -> dict[str, Any]:
    """填充可选字段默认值，不覆盖用户显式传入的值。"""
    filled = dict(params)
    for key, default in _OPTIONAL_DEFAULTS.items():
        if key not in filled or filled[key] is None or filled[key] == "":
            filled[key] = default
    return filled


def _parse_clean_output(stdout: str) -> dict[str, Any]:
    """从 engine.py 的 stdout 中解析执行结果。

    engine.py 不输出 JSON summary，但会输出：
    - 每步的 📌 变量值
    - 最终 ✅ 或 ❌ 状态
    - 中间的错误信息
    
    返回结构化的解析结果。
    """
    result: dict[str, Any] = {
        "steps_extracted": {},
        "final_status": "UNKNOWN",
        "errors": [],
        "raw_stdout": stdout[-3000:] if len(stdout) > 3000 else stdout,
    }
    
    lines = stdout.strip().split("\n")
    for line in lines:
        line = line.strip()
        # 提取 📌 变量
        if line.startswith("📌"):
            # 格式：📌 key = value
            parts = line[2:].split("=", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()
                result["steps_extracted"][key] = value
        # 提取最终状态
        # 注意：flow.py 命中 terminal 时直接 return，永远不会打印 "✅ 流程执行完毕"，
        # 只会打印 terminal.message（如 "✅ SRM 寻源价格造数完成"）。此处两种都认。
        elif line.startswith("✅ 流程执行完毕") or line.startswith("✅ SRM 寻源价格造数完成"):
            result["final_status"] = "SUCCESS"
        elif line.startswith("❌ 步骤"):
            result["final_status"] = "FAILED"
            result["errors"].append(line)
        elif "❌" in line and ("错误" in line or "失败" in line):
            result["errors"].append(line)
    
    return result


def _assert_clean_result(parsed: dict[str, Any]) -> tuple[bool, str]:
    """断言清洗结果，返回 (passed, detail)。
    
    基于 _parse_clean_output 的解析结果判断：
    - final_status == SUCCESS 且无错误 → 通过
    - 提取到了关键变量（price_id, price_type_data 等）→ 通过
    """
    if not parsed:
        return False, "清洗引擎未返回有效结果"

    errors = parsed.get("errors", [])
    final_status = parsed.get("final_status", "UNKNOWN")
    extracted = parsed.get("steps_extracted", {})

    # 有明确的错误 → 失败
    if errors:
        return False, f"清洗执行出错: {'; '.join(errors[:3])}"

    # 明确失败 → 失败
    if final_status == "FAILED":
        return False, "清洗流程执行失败"

    # ── 过程闸：不回查=没做 ──
    # 「提取到 N 个变量」只代表流程跑完了每一步，不代表这些步骤拿到了真实数据。
    # mify HTTP 通道对部分接口会丢响应体，导致回查变量值为空（None / '' / {'_raw': ''}）。
    # 这种情况下即便 final_status=SUCCESS，也必须判为「无法确认」，绝不谎报 priceReady。
    def _is_empty(v: Any) -> bool:
        # stdout 里变量值是字符串化的，空态包括：None、空串、空 dict、{'_raw': ''}
        if v is None:
            return True
        s = str(v).strip()
        return s in ("", "None", "{}", "{'_raw': ''}", '{"_raw": ""}')

    # 回查类关键变量：任一非空，才说明 SRM 侧真的返回了可核对的数据
    verify_keys = ("asl_verify", "final_verify", "price_id", "detection_result")
    verify_vals = {k: extracted.get(k) for k in verify_keys if k in extracted}
    has_real_verify = any(not _is_empty(v) for v in verify_vals.values())

    if not has_real_verify:
        # 回查全空：无法确认 ASL/定价单是否真建成 → 判为失败（诚实报告，让下游降级或阻断）
        empty_summary = ", ".join(f"{k}=空" for k in verify_vals) or "无回查变量"
        return False, (
            f"回查未拿到真实数据（{empty_summary}）；"
            "疑似 mify 通道丢响应体，无法确认 ASL/定价单是否生效，不放行 priceReady"
        )

    # 走到这：回查拿到了非空数据
    if final_status == "SUCCESS":
        return True, f"清洗断言通过（回查命中真实数据，提取 {len(extracted)} 个变量）"
    # 状态未知但回查有真实数据 → 保守通过并标注
    return True, f"回查命中真实数据（{len(verify_vals)} 项非空），流程未报终态，谨慎放行"


def run_srm_price_clean(
    config: str,
    params: dict[str, Any],
    run_dir: Path,
    dry_run: bool = False,
) -> StepResult:
    """执行 SRM 寻源价格清洗。

    流程：校验输入 → 填充默认值 → 执行清洗 → 断言结果
    返回 StepResult，status 为 SUCCESS / FAILED / SKIPPED。
    """
    # ── 阶段 1：输入校验 ──
    errors = _validate_inputs(params)
    if errors:
        detail = "输入校验失败: " + "; ".join(errors)
        result = StepResult(
            name="srm_price_clean",
            status="FAILED",
            detail=detail,
            data={"errors": errors, "params": params},
        )
        write_json(run_dir / "srm-price-clean-result.json", result.to_dict())
        print(f"  ❌ {detail}")
        return result

    # ── 阶段 2：填充默认值 ──
    filled_params = _fill_defaults(params)

    # ── 阶段 3：构建命令 ──
    command = [sys.executable, str(ROOT / "engine.py"), config]
    for key, value in filled_params.items():
        command.extend([
            f"--{key}",
            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False),
        ])

    if dry_run:
        result = StepResult(
            name="srm_price_clean",
            status="SKIPPED",
            detail="dry-run 模式未真实执行 SRM 价格清洗",
            data={"command": command, "filled_params": filled_params},
        )
        write_json(run_dir / "srm-price-clean-result.json", result.to_dict())
        return result

    # ── 阶段 4：执行清洗 ──
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=120,  # 2 分钟超时，清洗流程比造数轻量
        )
        # ── 阶段 5：解析输出 ──
        parsed = _parse_clean_output(completed.stdout)
        assert_passed, assert_detail = _assert_clean_result(parsed)

        if completed.returncode != 0:
            status = "FAILED"
            detail = f"SRM 价格清洗失败 (rc={completed.returncode}): {assert_detail}"
        elif not assert_passed:
            status = "FAILED"
            detail = f"清洗执行完成但断言失败: {assert_detail}"
        else:
            status = "SUCCESS"
            detail = f"SRM 价格清洗完成: {assert_detail}"

        result = StepResult(
            name="srm_price_clean",
            status=status,
            detail=detail,
            data={
                "returncode": completed.returncode,
                "command": command,
                "assert_passed": assert_passed,
                "assert_detail": assert_detail,
                "stdout": completed.stdout[-2000:] if len(completed.stdout) > 2000 else completed.stdout,
                "stderr": completed.stderr[-1000:] if len(completed.stderr) > 1000 else completed.stderr,
                "parsed": parsed,
            },
        )
    except subprocess.TimeoutExpired:
        result = StepResult(
            name="srm_price_clean",
            status="FAILED",
            detail="SRM 价格清洗执行超时（2 分钟上限）",
            data={"command": command, "timeout": 120},
        )
    write_json(run_dir / "srm-price-clean-result.json", result.to_dict())

    icon = "✅" if result.status == "SUCCESS" else "❌"
    print(f"  {icon} {result.detail}")
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
