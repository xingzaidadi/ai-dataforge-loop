#!/usr/bin/env python3
"""Multimodal closed-loop orchestrator for data-making workflows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Windows 控制台默认 GBK，无法编码 ▶/emoji 等字符；统一强制 UTF-8 输出
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

from common import StepResult, ensure_run_dir, make_run_id, parse_kv_pairs, write_json
from datamake_runner import run_datamake
from evidence_pack import build_evidence_pack
from failure_diagnose import diagnose_failure
from screenshot_params_adapter import adapt_file
from srm_asn_create import run_srm_asn_create
from srm_price_clean import run_srm_price_clean
from srm_pull_command import run_srm_pull_command
from ui_verify import verify_ui
from vision_extract import extract_intent


def _merge_params(extracted: dict[str, Any], explicit: dict[str, Any]) -> dict[str, Any]:
    merged = {}
    intent = extracted.get("intent")
    if isinstance(intent, dict):
        merged.update({key: value for key, value in intent.items() if key not in {"sourceType", "purchaseOrgCN"}})
    merged.update(explicit)
    return merged


def _flatten_for_clean(params: dict[str, Any]) -> dict[str, Any]:
    """将 engine params 展平为 srm_price_clean 需要的扁平格式。

    srm_price_clean 要求 materialCode (str)、purchaseOrg、supplierCode 等扁平字段；
    而 engine params 使用 materials (dict: {materialCode1: ..., materialCode2: ...})。
    此函数提取第一个物料编码作为 materialCode，确保清洗校验通过。
    """
    flat = dict(params)
    materials = params.get("materials")
    if isinstance(materials, dict):
        # 取第一个物料编码作为 materialCode
        for key in ("materialCode1", "materialCode", "code"):
            if key in materials and materials[key]:
                flat["materialCode"] = materials[key]
                break
    elif isinstance(materials, str) and materials:
        flat["materialCode"] = materials
    # 确保 stockOrg 映射到 purchaseOrg（清洗器用 purchaseOrg 做校验）
    if not flat.get("purchaseOrg") and flat.get("stockOrg"):
        flat["purchaseOrg"] = flat["stockOrg"]
    return flat


def _extract_po_no(datamake_result: Any) -> str | None:
    """从阶段1造数结果中提取 SCM PO 号（purchase_order_no，如 6000...），供阶段2 状态判定。"""
    business = {}
    if datamake_result and isinstance(datamake_result.data, dict):
        business = datamake_result.data.get("businessData", {}) or {}
    return business.get("poNo")


def _extract_erp_no(datamake_result: Any) -> str | None:
    """从阶段1造数结果中提取 ERP 采购单号（erpNo，如 4500...）。

    ⚠️ 阶段3 SRM 场景接口（scene/execute、newGetByOptions 的 EBELN）只认 ERP 号，
    SCM 号（6000...）查不到数据。故 ASN 承接必须用此 ERP 号，不能用 poNo。
    """
    business = {}
    if datamake_result and isinstance(datamake_result.data, dict):
        business = datamake_result.data.get("businessData", {}) or {}
    return business.get("erpNo")


def _evaluate_po_ready(datamake_result: Any, dry_run: bool,
                       existing_po_no: str | None = None) -> StepResult:
    """阶段2 · PO Ready Gate — 审批状态闸门（非新系统，仅状态判定）。

    dry-run：占位放行；真实模式：依据造数结果的审批状态判定是否放行 ASN。
    existing-po 模式：跳过阶段1造数，用户直接提供已审批 PO，凭 existing_po_no 放行。
    """
    po_no = _extract_po_no(datamake_result) or existing_po_no
    # 阶段3 ASN 用 ERP 号；existing-po 模式用户可用 poNo 直接给 ERP 号（自带已审批 PO 场景）
    erp_no = _extract_erp_no(datamake_result) or existing_po_no
    # existing-po 模式：造数被跳过，用户自带已审批 PO——优先于 dry-run 判定，
    # 使 existing-po + dry-run 也如实显示 EXISTING（沿用已审批 PO），而非笼统的 DRYRUN。
    if existing_po_no and (datamake_result is None or datamake_result.status == "SKIPPED"):
        detail = f"existing-po 模式：沿用已审批 PO {existing_po_no}，可承接 ASN"
        if dry_run:
            detail += "（dry-run 预检）"
        return StepResult(
            name="po_ready_gate",
            status="SUCCESS",
            detail=detail,
            data={"approved": True, "approvalStatus": "EXISTING",
                  "poNo": existing_po_no, "erpNo": erp_no},
        )
    if dry_run:
        return StepResult(
            name="po_ready_gate",
            status="SUCCESS",
            detail="dry-run 模式：PO Ready Gate 占位放行",
            data={
                "approved": True,
                "approvalStatus": "DRYRUN",
                "poNo": po_no or "PO-DRYRUN-PLACEHOLDER",
                "erpNo": erp_no or "ERP-DRYRUN-PLACEHOLDER",
            },
        )
    if datamake_result and datamake_result.status == "SUCCESS" and po_no:
        return StepResult(
            name="po_ready_gate",
            status="SUCCESS",
            detail=f"PO {po_no} 已就绪，可承接 ASN",
            data={"approved": True, "approvalStatus": "APPROVED",
                  "poNo": po_no, "erpNo": erp_no},
        )
    return StepResult(
        name="po_ready_gate",
        status="FAILED",
        detail="PO 未就绪（造数失败或无 PO 号），ASN 不放行",
        data={"approved": False, "approvalStatus": "NOT_READY",
              "poNo": po_no, "erpNo": erp_no},
    )


def _flatten_for_pull_command(params: dict[str, Any]) -> dict[str, Any]:
    """将闭环参数展平为 srm_pull_command 需要的拉料指令入参。

    拉料指令场景要 materialCode1（engine 用 materials dict），并透传
    交料模式/预占模式/目的地/项目编码/采组等分支字段。
    """
    flat = dict(params)
    materials = params.get("materials")
    if isinstance(materials, dict):
        for src, dst in (("materialCode1", "materialCode1"), ("materialCode2", "materialCode2")):
            if materials.get(src) and not flat.get(dst):
                flat[dst] = materials[src]
        # 单物料时 materials 可能只有 materialCode1/materialCode/code
        if not flat.get("materialCode1"):
            for key in ("materialCode1", "materialCode", "code"):
                if materials.get(key):
                    flat["materialCode1"] = materials[key]
                    break
    elif isinstance(materials, str) and materials and not flat.get("materialCode1"):
        flat["materialCode1"] = materials
    return flat


def _flatten_for_asn(params: dict[str, Any], erp_no: str | None) -> dict[str, Any]:
    """将闭环参数展平为 srm_asn_create 需要的 ASN 承接参数。

    ⚠️ ASN 的 poNo 字段传的是 ERP 采购单号（4500...），非 SCM 号——SRM 场景接口只认 ERP 号。
    erp_no 为空时回退到 params.poNo（独立运行/existing-po 时用户可能直接给 ERP 号）。
    """
    flat = {"poNo": erp_no or params.get("poNo")}
    for key in ("pullCommand", "warehouseId", "supplierCode", "bsart", "matkl",
                "lineCount", "asnCategory", "taskType", "sceneId", "sceneName", "taskId"):
        if params.get(key) not in (None, ""):
            flat[key] = params[key]
    return flat


def _build_chain_summary(pre_clean_result, datamake_result, po_ready_result, asn_result,
                         dry_run: bool = False, pull_command_result=None) -> dict[str, Any]:
    """汇总全链路关键单号与放行状态，供证据包与结果卡片直接消费。

    dry-run 下没有真实单号，用占位值填充四个关键键（priceReady/prNo/poNo/zasnNo），
    使证据包结构完整、可截图演示。
    """
    dm_business = {}
    if datamake_result and isinstance(datamake_result.data, dict):
        dm_business = datamake_result.data.get("businessData", {}) or {}
    asn_business = {}
    if asn_result and isinstance(asn_result.data, dict):
        asn_business = asn_result.data.get("businessData", {}) or {}
    price_ready = None
    if pre_clean_result:
        price_ready = pre_clean_result.status in {"SUCCESS", "SKIPPED"}
    ph = (lambda real, placeholder: real if real else (placeholder if dry_run else None))
    # ASN 被阻断/失败时，绝不给占位单号——否则报告会把"场景未接入"显示成"已有 ASN"（谎报）
    asn_not_done = asn_result is not None and asn_result.status in {"BLOCKED", "FAILED"}
    zasn_no = None if asn_not_done else ph(asn_business.get("zasnNo"), "ASN-DRYRUN-PLACEHOLDER")
    pull_business = {}
    if pull_command_result and isinstance(pull_command_result.data, dict):
        pull_business = pull_command_result.data.get("businessData", {}) or {}
    # 拉料指令未成功（FAILED/BLOCKED）时不给占位号，避免谎报
    pull_not_done = pull_command_result is not None and pull_command_result.status in {"BLOCKED", "FAILED"}
    command_code = None if pull_not_done else pull_business.get("commandCode")
    return {
        "priceReady": price_ready,
        "prNo": ph(dm_business.get("prNo"), "PR-DRYRUN-PLACEHOLDER"),
        "poNo": ph(dm_business.get("poNo") or po_ready_result.data.get("poNo"), "PO-DRYRUN-PLACEHOLDER"),
        "erpNo": ph(dm_business.get("erpNo") or po_ready_result.data.get("erpNo"), "ERP-DRYRUN-PLACEHOLDER"),
        "approved": po_ready_result.data.get("approved"),
        "commandCode": command_code,
        "asnScene": asn_business.get("asnScene"),
        "zasnNo": zasn_no,
    }


def run_closed_loop(
    config: str,
    params: dict[str, Any],
    text: str = "",
    image: str | None = None,
    sop: str | None = None,
    ui_config: str | None = None,
    pre_clean_config: str | None = None,
    pull_command_config: str | None = None,
    asn_config: str | None = None,
    screenshot_json: str | None = None,
    skip_pre_clean: bool = False,
    strict_pre_clean: bool = False,
    skip_pull_command: bool = False,
    skip_asn: bool = False,
    skip_datamake: bool = False,
    dry_run: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or make_run_id()
    run_dir = ensure_run_dir(run_id)

    intent_result = extract_intent(text=text, image=image, sop=sop)
    write_json(run_dir / "intent.json", intent_result.to_dict())
    final_params = _merge_params(intent_result.data, params)
    screenshot_params_result = None
    if screenshot_json:
        screenshot_params_result = adapt_file(
            Path(screenshot_json),
            run_dir / "screenshot-params-result.json",
        )
        final_params.update(screenshot_params_result.data.get("engineParams", {}))
        final_params.update(params)
    write_json(run_dir / "params.json", {"params": final_params, "config": config})

    # ── 阶段 0：SRM Sourcing Readiness Gate（寻源价格前置治理，可选）──
    pre_clean_result = None
    if not skip_pre_clean and pre_clean_config:
        print("▶ 阶段0 · SRM Sourcing Readiness Gate（寻源价格前置治理）")
        clean_params = _flatten_for_clean(final_params)
        pre_clean_result = run_srm_price_clean(
            config=pre_clean_config,
            params=clean_params,
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
            if strict_pre_clean:
                # 严格模式：前置治理失败即阻断下游，不硬造 PRPO
                print(f"  ⛔ 前置清洗失败（严格模式，阻断下游）: {warning_msg}")
                summary = {
                    "runId": run_id,
                    "status": "BLOCKED",
                    "config": config,
                    "runDir": str(run_dir),
                    "intent": intent_result.to_dict(),
                    "preClean": pre_clean_result.to_dict(),
                    "warnings": [f"前置清洗失败（严格模式阻断）: {warning_msg}"],
                }
                write_json(run_dir / "summary.json", summary)
                evidence_result = build_evidence_pack(run_dir)
                summary["evidence"] = evidence_result.to_dict()
                summary["report"] = evidence_result.data.get("report")
                write_json(run_dir / "summary.json", summary)
                return summary
            # 默认降级模式：记录警告，降级继续造数
            print(f"  ⚠️ 前置清洗失败，降级继续造数: {warning_msg}")

    # ── 阶段 1：PRPO 造数 ──
    existing_po_no = final_params.get("poNo") if skip_datamake else None
    if skip_datamake:
        print("▶ 阶段1 · PRPO 造数（SAP）— existing-po 模式跳过，沿用已审批 PO")
        datamake_result = StepResult(
            name="datamake",
            status="SKIPPED",
            detail=f"existing-po 模式：跳过造数，沿用已审批 PO {existing_po_no}",
            data={"businessData": {"poNo": existing_po_no}},
        )
        write_json(run_dir / "datamake-result.json", datamake_result.to_dict())
    else:
        print("▶ 阶段1 · PRPO 造数（SAP）")
        datamake_result = run_datamake(config=config, params=final_params, run_dir=run_dir, dry_run=dry_run)

    # ── 阶段 2：PO Ready Gate（审批状态闸门，非新系统）──
    print("▶ 阶段2 · PO Ready Gate（审批状态闸门）")
    po_ready_result = _evaluate_po_ready(datamake_result, dry_run=dry_run, existing_po_no=existing_po_no)
    write_json(run_dir / "po-ready-result.json", po_ready_result.to_dict())
    po_no = po_ready_result.data.get("poNo")
    erp_no = po_ready_result.data.get("erpNo")

    # ── 阶段 2.5：SRM 侧 拉料指令创建（大货 ZNB → CIN ASN 前置）──
    # 规范链路：PO 建成后建拉料指令拿 commandCode(4500...)，阶段3 ASN 用它当 pullCommand。
    # 仅在 PO 就绪 + 配了 pull-command-config 时执行；采组含 111K 的会在工具内自行豁免跳过。
    pull_command_result = None
    if not skip_pull_command and pull_command_config and po_ready_result.data.get("approved"):
        print("▶ 阶段2.5 · SRM 侧 拉料指令创建")
        pull_params = _flatten_for_pull_command(final_params)
        pull_command_result = run_srm_pull_command(
            config=pull_command_config,
            params=pull_params,
            run_dir=run_dir,
            dry_run=dry_run,
        )
        pull_biz = pull_command_result.data.get("businessData", {}) if isinstance(pull_command_result.data, dict) else {}
        command_code = pull_biz.get("commandCode")
        # 拿到真实 commandCode → 注入 pullCommand，并强制阶段3 ASN 走大货(CIN)承接。
        # ⚠️ 为何强制 CIN：本单既然建了拉料指令，承接路径就是「根据拉料指令创建ASN」(CIN/378 场景，
        #    有 __pullCommand__ 槽)；而 resolve_category 对高通/TI/MTK 供应商默认优先返回 EDI 类别
        #    (GAOTONG/369，无 pullCommand 槽)——那条路不消费 commandCode，正是 WS-14 撞墙的原因。
        #    此处仅对"本单已建拉料指令"这一事实显式改判，不动全局供应商优先级（真 EDI 单不受影响）。
        if command_code and command_code != "PULLCMD-DRYRUN-PLACEHOLDER" and not final_params.get("pullCommand"):
            final_params["pullCommand"] = command_code
            final_params["asnCategory"] = "CIN"
            print(f"  🔗 拉料指令 commandCode={command_code} → 注入 ASN pullCommand + 强制 CIN 大货承接")
        elif pull_command_result.status == "SKIPPED":
            pass  # 采组豁免/ dry-run：不阻断，ASN 走原有分类
        elif not command_code:
            print("  ⚠️ 未取到 commandCode，阶段3 ASN 将按无拉料指令分类（非 CIN）")

    # ── 阶段 3：SRM 侧 ASN 承接 ──
    asn_result = None
    if not skip_asn and asn_config:
        print("▶ 阶段3 · SRM 侧 ASN 承接")
        if po_ready_result.data.get("approved"):
            asn_params = _flatten_for_asn(final_params, erp_no)
            asn_result = run_srm_asn_create(
                config=asn_config,
                params=asn_params,
                run_dir=run_dir,
                dry_run=dry_run,
            )
        else:
            asn_result = StepResult(
                name="srm_asn_create",
                status="FAILED",
                detail=f"PO Ready Gate 未放行（{po_ready_result.data.get('approvalStatus')}），跳过 ASN 承接",
                data={"skipped": True, "reason": po_ready_result.detail},
            )
            write_json(run_dir / "asn-result.json", asn_result.to_dict())
            print(f"  ⚠️ {asn_result.detail}")

    # ── 阶段 4：UI 验收 ──
    print("▶ 阶段4 · UI 验收")
    ui_context = dict(final_params)
    ui_context["runId"] = run_id
    ui_verify_result = verify_ui(run_dir=run_dir, config_path=ui_config, context=ui_context, dry_run=dry_run)

    # ── 阶段 5：失败诊断 ──
    diagnosis_result = None
    if datamake_result.status == "FAILED" or ui_verify_result.status == "FAILED" or (
        asn_result and asn_result.status == "FAILED"
    ):
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
    else:
        if pull_command_result and pull_command_result.status in {"FAILED", "BLOCKED"}:
            overall_status = "PARTIAL"
            clean_warnings.append(
                f"拉料指令创建{'失败' if pull_command_result.status == 'FAILED' else '阻断'}: {pull_command_result.detail}"
            )
        if asn_result and asn_result.status == "FAILED":
            overall_status = "PARTIAL"
            clean_warnings.append(
                f"ASN 承接失败: {asn_result.detail}"
            )
        elif asn_result and asn_result.status == "BLOCKED":
            overall_status = "PARTIAL"
            clean_warnings.append(
                f"ASN 承接阻断（场景未接入）: {asn_result.detail}"
            )
        if ui_verify_result.status == "FAILED":
            overall_status = "PARTIAL"
            clean_warnings.append(
                f"UI验收失败: {ui_verify_result.detail}"
            )
    chain = _build_chain_summary(pre_clean_result, datamake_result, po_ready_result, asn_result,
                                 dry_run, pull_command_result)
    summary = {
        "runId": run_id,
        "status": overall_status,
        "config": config,
        "runDir": str(run_dir),
        # DoD 四个关键键在顶层冗余一份（同时保留在 chain 下），便于验收直接 jq .poNo summary.json
        "priceReady": chain["priceReady"],
        "prNo": chain["prNo"],
        "poNo": chain["poNo"],
        "zasnNo": chain["zasnNo"],
        "intent": intent_result.to_dict(),
        "screenshotParams": screenshot_params_result.to_dict() if screenshot_params_result else None,
        "preClean": pre_clean_result.to_dict() if pre_clean_result else None,
        "datamake": datamake_result.to_dict(),
        "poReady": po_ready_result.to_dict(),
        "pullCommand": pull_command_result.to_dict() if pull_command_result else None,
        "asn": asn_result.to_dict() if asn_result else None,
        "uiVerify": ui_verify_result.to_dict(),
        "diagnosis": diagnosis_result.to_dict() if diagnosis_result else None,
        "warnings": clean_warnings if clean_warnings else None,
        "chain": chain,
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
    parser.add_argument("--pre-clean-config", default=None, help="阶段0 SRM 寻源价格前置治理配置")
    parser.add_argument("--pull-command-config", default=None,
                        help="阶段2.5 SRM 侧 拉料指令创建配置（大货 ZNB → CIN ASN 前置）")
    parser.add_argument("--asn-config", default=None, help="阶段3 SRM 侧 ASN 承接配置")
    parser.add_argument("--screenshot-json", help="OpenClaw 多模态截图识别后的 JSON 文件")
    parser.add_argument("--skip-pre-clean", action="store_true", help="跳过阶段0 前置治理")
    parser.add_argument("--strict-pre-clean", action="store_true",
                        help="严格模式：阶段0 前置治理失败即阻断下游（默认降级继续造数并标 PARTIAL）")
    parser.add_argument("--skip-pull-command", action="store_true", help="跳过阶段2.5 拉料指令创建")
    parser.add_argument("--skip-asn", action="store_true", help="跳过阶段3 ASN 承接")
    parser.add_argument("--asn-mode", choices=["auto", "existing-po"], default="auto",
                        help="ASN 承接模式：auto=全链路承接；existing-po=已有PO直接建ASN")
    parser.add_argument("--dry-run", action="store_true", help="预检模式：不真实造数、不打开浏览器")
    parser.add_argument("params", nargs="*", help="显式造数参数 key=value，会覆盖识别结果")
    args = parser.parse_args()

    # existing-po 模式：用户已有 PO，跳过阶段0/1（前置治理与造数），直接承接 ASN
    existing_po = args.asn_mode == "existing-po"
    skip_pre_clean = args.skip_pre_clean or existing_po

    summary = run_closed_loop(
        config=args.config,
        params=parse_kv_pairs(args.params),
        text=args.text,
        image=args.image,
        sop=args.sop,
        ui_config=args.ui_config,
        pre_clean_config=args.pre_clean_config,
        pull_command_config=args.pull_command_config,
        asn_config=args.asn_config,
        screenshot_json=args.screenshot_json,
        skip_pre_clean=skip_pre_clean,
        strict_pre_clean=args.strict_pre_clean,
        skip_pull_command=args.skip_pull_command,
        skip_asn=args.skip_asn,
        skip_datamake=existing_po,
        dry_run=args.dry_run,
        run_id=args.run_id,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] in {"SUCCESS", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
