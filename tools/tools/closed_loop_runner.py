#!/usr/bin/env python3
"""Multimodal closed-loop orchestrator for data-making workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import ensure_run_dir, make_run_id, parse_kv_pairs, write_json
from datamake_runner import run_datamake
from evidence_pack import build_evidence_pack
from failure_diagnose import diagnose_failure
from srm_price_clean import run_srm_price_clean
from ui_verify import verify_ui
from vision_extract import extract_intent


def _merge_params(extracted: dict[str, Any], explicit: dict[str, Any]) -> dict[str, Any]:
    merged = {}
    intent = extracted.get("intent")
    if isinstance(intent, dict):
        merged.update({key: value for key, value in intent.items() if key not in {"sourceType", "purchaseOrgCN"}})
    merged.update(explicit)
    return merged


def run_closed_loop(
    config: str,
    params: dict[str, Any],
    text: str = "",
    image: str | None = None,
    sop: str | None = None,
    ui_config: str | None = None,
    pre_clean_config: str | None = None,
    skip_pre_clean: bool = False,
    dry_run: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or make_run_id()
    run_dir = ensure_run_dir(run_id)

    intent_result = extract_intent(text=text, image=image, sop=sop)
    write_json(run_dir / "intent.json", intent_result.to_dict())
    final_params = _merge_params(intent_result.data, params)
    write_json(run_dir / "params.json", {"params": final_params, "config": config})

    # ── 阶段 0：PRPO 前置数据清洗（可选）──
    pre_clean_result = None
    if not skip_pre_clean and pre_clean_config:
        pre_clean_result = run_srm_price_clean(
            config=pre_clean_config,
            params=final_params,
            run_dir=run_dir,
            dry_run=dry_run,
        )
        # srm_price_clean.py 已写入 srm-price-clean-result.json，此处不再重复写
        if pre_clean_result.status == "FAILED":
            # 清洗失败：记录警告，降级继续造数
            clean_errors = pre_clean_result.data.get("errors", [])
            assert_detail = pre_clean_result.data.get("assert_detail", "")
            warning_parts = []
            if clean_errors:
                warning_parts.append(f"输入校验: {'; '.join(clean_errors)}")
            if assert_detail:
                warning_parts.append(f"断言: {assert_detail}")
            warning_msg = "; ".join(warning_parts) if warning_parts else pre_clean_result.detail
            print(f"  ⚠️ 前置清洗失败，降级继续造数: {warning_msg}")

    # ── 阶段 1：PRPO 造数 ──
    datamake_result = run_datamake(config=config, params=final_params, run_dir=run_dir, dry_run=dry_run)

    # ── 阶段 2：UI 验收 ──
    ui_context = dict(final_params)
    ui_context["runId"] = run_id
    ui_verify_result = verify_ui(run_dir=run_dir, config_path=ui_config, context=ui_context, dry_run=dry_run)

    # ── 阶段 3：失败诊断 ──
    diagnosis_result = None
    if datamake_result.status == "FAILED" or ui_verify_result.status == "FAILED":
        diagnosis_result = diagnose_failure(run_dir)

    overall_status = "SUCCESS"
    clean_warnings = []
    if pre_clean_result and pre_clean_result.status == "FAILED":
        overall_status = "PARTIAL"
        clean_warnings.append(
            f"前置清洗失败: {pre_clean_result.detail}"
        )
    if datamake_result.status == "FAILED":
        overall_status = "FAILED"
        clean_warnings.append(
            f"造数失败: {datamake_result.detail}"
        )
    elif ui_verify_result.status == "FAILED":
        overall_status = "PARTIAL"
        clean_warnings.append(
            f"UI验收失败: {ui_verify_result.detail}"
        )
    summary = {
        "runId": run_id,
        "status": overall_status,
        "config": config,
        "runDir": str(run_dir),
        "intent": intent_result.to_dict(),
        "preClean": pre_clean_result.to_dict() if pre_clean_result else None,
        "datamake": datamake_result.to_dict(),
        "uiVerify": ui_verify_result.to_dict(),
        "diagnosis": diagnosis_result.to_dict() if diagnosis_result else None,
        "warnings": clean_warnings if clean_warnings else None,
    }
    write_json(run_dir / "summary.json", summary)
    evidence_result = build_evidence_pack(run_dir)
    summary["evidence"] = evidence_result.to_dict()
    summary["report"] = evidence_result.data.get("report")
    summary["reportIndex"] = evidence_result.data.get("index")
    write_json(run_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 数据智造多模态闭环入口")
    parser.add_argument("--config", default="configs/znb-prpo.yaml", help="造数流程配置")
    parser.add_argument("--ui-config", default="configs/ui-verify-prpo.yaml", help="UI 验收配置")
    parser.add_argument("--text", default="", help="用户口述需求")
    parser.add_argument("--image", help="页面/SOP/失败截图路径")
    parser.add_argument("--sop", help="SOP 文本路径")
    parser.add_argument("--run-id", help="指定 run id")
    parser.add_argument("--pre-clean-config", default=None, help="PRPO 前置数据清洗配置")
    parser.add_argument("--skip-pre-clean", action="store_true", help="跳过前置清洗")
    parser.add_argument("--dry-run", action="store_true", help="预检模式：不真实造数、不打开浏览器")
    parser.add_argument("params", nargs="*", help="显式造数参数 key=value，会覆盖识别结果")
    args = parser.parse_args()

    summary = run_closed_loop(
        config=args.config,
        params=parse_kv_pairs(args.params),
        text=args.text,
        image=args.image,
        sop=args.sop,
        ui_config=args.ui_config,
        pre_clean_config=args.pre_clean_config,
        skip_pre_clean=args.skip_pre_clean,
        dry_run=args.dry_run,
        run_id=args.run_id,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] in {"SUCCESS", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
