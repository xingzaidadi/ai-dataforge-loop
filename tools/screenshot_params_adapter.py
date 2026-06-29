#!/usr/bin/env python3
"""Adapt OpenClaw multimodal JSON into ai-dataforge-loop parameters."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import StepResult, read_json, write_json  # noqa: E402


ORG_MAP = {
    "手机": ("MI_PHONE", "1110"),
    "生态链": ("MI_IOT", "2120"),
    "iot": ("MI_IOT", "2120"),
    "loT": ("MI_IOT", "2120"),
    "lot": ("MI_IOT", "2120"),
    "可穿戴": ("MI_WEAR", "111J"),
    "笔记本": ("MI_NOTEBOOK", "111K"),
    "电视": ("MI_TV", "1111"),
    "空调": ("MI_AIRCONDITION", "1131"),
    "空调m5": ("MI_AIRCONDITION_M5", "1134"),
    "冰箱": ("MI_REFRIGERATOR", "1132"),
    "洗衣机": ("MI_LAUNDRYCARE", "1133"),
    "汽车电子": ("MI_AUTOEACC", "111N"),
}

VALID_NEXT_ACTIONS = {
    "ASK_MISSING_FIELDS",
    "AUTO_FILL_FROM_POOL",
    "RUN_PRE_CLEAN",
    "RUN_DATAMAKE",
}

REQUIRED_FOR_DATAMAKE = ["sceneType", "stockOrg", "purchaseOrg", "supplierCode", "materials"]


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return ""


def _org_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_org(data: dict[str, Any]) -> None:
    stock_org = str(data.get("stockOrg") or "").strip()
    purchase_org = str(data.get("purchaseOrg") or "").strip()
    candidates = [
        data.get("stockOrgCN"),
        data.get("purchaseOrgCN"),
        data.get("demandOrg"),
        data.get("stockOrg"),
        data.get("purchaseOrg"),
    ]
    for candidate in candidates:
        key = _org_key(candidate)
        if key in ORG_MAP:
            mapped_stock, mapped_purchase = ORG_MAP[key]
            data["stockOrg"] = stock_org or mapped_stock
            data["purchaseOrg"] = purchase_org or mapped_purchase
            return


def _normalize_materials(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_materials = data.get("materials")
    materials: list[dict[str, Any]] = []
    if isinstance(raw_materials, list):
        for item in raw_materials:
            if not isinstance(item, dict):
                continue
            material_code = _first_non_empty(item.get("materialCode"), item.get("mpn"), item.get("code"))
            if not material_code:
                continue
            materials.append({
                "materialCode": str(material_code),
                "materialName": item.get("materialName", ""),
                "quantity": _first_non_empty(item.get("quantity"), data.get("quantity"), "1"),
                "unitPrice": item.get("unitPrice", ""),
                "currency": item.get("currency", data.get("currency", "")),
            })
    elif isinstance(raw_materials, dict):
        for value in raw_materials.values():
            if isinstance(value, dict):
                material_code = _first_non_empty(value.get("materialCode"), value.get("code"))
                if material_code:
                    materials.append({
                        "materialCode": str(material_code),
                        "materialName": value.get("materialName", ""),
                        "quantity": _first_non_empty(value.get("quantity"), data.get("quantity"), "1"),
                        "unitPrice": value.get("unitPrice", ""),
                        "currency": value.get("currency", data.get("currency", "")),
                    })
            elif value:
                materials.append({
                    "materialCode": str(value),
                    "materialName": "",
                    "quantity": _first_non_empty(data.get("quantity"), "1"),
                    "unitPrice": "",
                    "currency": data.get("currency", ""),
                })
    else:
        material_code = _first_non_empty(data.get("materialCode"), data.get("mpn"))
        if material_code:
            materials.append({
                "materialCode": str(material_code),
                "materialName": data.get("materialName", ""),
                "quantity": _first_non_empty(data.get("quantity"), "1"),
                "unitPrice": data.get("unitPrice", ""),
                "currency": data.get("currency", ""),
            })
    return materials


def _materials_for_engine(materials: list[dict[str, Any]]) -> dict[str, str]:
    return {
        f"materialCode{index}": str(item["materialCode"])
        for index, item in enumerate(materials, start=1)
        if item.get("materialCode")
    }


# Scene-specific required fields (derived from YAML configs + templates)
# shipLocCode: only required for ZSC/ZYZ/ZDO (used to query d_factory → receiveFactoryId)
#              NOT required for ZNB (template doesn't use it) or ZWW (uses SKU instead)
# projectCode: optional for all scenes (template uses it if present, omits if empty)
SCENE_SHIPLOCCODE_REQUIRED = {"ZSC", "ZYZ", "ZDO"}


def _missing_fields(data: dict[str, Any], materials: list[dict[str, Any]]) -> list[str]:
    missing = set(data.get("missingFields") or [])
    # Core fields always required
    for field in ["sceneType", "stockOrg", "purchaseOrg", "supplierCode"]:
        if not data.get(field):
            missing.add(field)
    if not materials:
        missing.add("materials")
    # shipLocCode: only required for scenes that query d_factory
    scene = str(data.get("sceneType") or data.get("orderType") or "").strip().upper()
    if scene in SCENE_SHIPLOCCODE_REQUIRED and not data.get("shipLocCode"):
        missing.add("shipLocCode")
    return sorted(str(item) for item in missing if item)


def adapt_screenshot_params(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize OpenClaw multimodal output and produce engine-ready params."""
    normalized = dict(data)
    normalized["orderType"] = _first_non_empty(normalized.get("orderType"), normalized.get("sceneType"))
    normalized["sceneType"] = _first_non_empty(normalized.get("sceneType"), normalized.get("orderType"))
    _normalize_org(normalized)

    materials = _normalize_materials(normalized)
    missing = _missing_fields(normalized, materials)
    can_proceed = not any(field in missing for field in REQUIRED_FOR_DATAMAKE)

    next_action = normalized.get("nextAction") or ""
    if next_action not in VALID_NEXT_ACTIONS:
        if normalized.get("detectedIssues") or normalized.get("repairAction"):
            next_action = "RUN_PRE_CLEAN"
        elif can_proceed:
            next_action = "RUN_DATAMAKE"
        else:
            next_action = "ASK_MISSING_FIELDS"

    engine_params = {
        "orderType": normalized.get("orderType"),
        "stockOrg": normalized.get("stockOrg"),
        "purchaseOrg": normalized.get("purchaseOrg"),
        "supplierCode": normalized.get("supplierCode"),
        "materials": _materials_for_engine(materials),
        "projectCode": normalized.get("projectCode"),
        "shipLocCode": normalized.get("shipLocCode"),
    }
    engine_params = {key: value for key, value in engine_params.items() if value not in (None, "", [], {})}

    return {
        "normalized": {
            **normalized,
            "materials": materials,
            "missingFields": missing,
            "nextAction": next_action,
            "canProceedToDatamake": can_proceed,
        },
        "engineParams": engine_params,
        "missingFields": missing,
        "nextAction": next_action,
        "canProceedToDatamake": can_proceed,
        "detectedIssues": normalized.get("detectedIssues") or [],
        "repairAction": normalized.get("repairAction") or "",
    }


def adapt_file(input_path: Path, output_path: Path | None = None) -> StepResult:
    data = read_json(input_path)
    # 如果输入已经是 StepResult 格式（name+status+data），提取内层 data 避免双重包装
    if isinstance(data, dict) and "data" in data and data.get("name"):
        inner = data["data"]
        if isinstance(inner, dict) and "engineParams" in inner:
            # 已适配过的文件，直接返回（不重新适配）
            result = StepResult(
                name="screenshot_params_adapter",
                status="SUCCESS",
                detail="输入已是适配后格式，直接使用",
                data=inner,
            )
            if output_path:
                write_json(output_path, result.to_dict())
            return result
    adapted = adapt_screenshot_params(data)
    result = StepResult(
        name="screenshot_params_adapter",
        status="SUCCESS",
        detail="OpenClaw 多模态参数已转换为造数参数",
        data=adapted,
    )
    if output_path:
        write_json(output_path, result.to_dict())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="转换 OpenClaw 截图识别 JSON 为造数参数")
    parser.add_argument("--input", required=True, help="OpenClaw 多模态输出 JSON")
    parser.add_argument("--output", help="适配结果输出路径")
    args = parser.parse_args()

    result = adapt_file(Path(args.input), Path(args.output) if args.output else None)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
