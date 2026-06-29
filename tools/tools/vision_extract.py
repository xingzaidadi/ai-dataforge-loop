#!/usr/bin/env python3
"""Extract data-making intent from text, SOP, or screenshot hints."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import StepResult, write_json


ORDER_TYPES = ["ZNB", "ZSC", "ZYZ", "ZDO", "ZWW"]
PURCHASE_ORG_MAP = {
    "生态链": {"stockOrg": "MI_IOT", "purchaseOrg": "2120"},
    "手机": {"stockOrg": "MI_PHONE", "purchaseOrg": "1110"},
    "可穿戴": {"stockOrg": "MI_WEAR", "purchaseOrg": "111J"},
    "笔记本": {"stockOrg": "MI_NOTEBOOK", "purchaseOrg": "111K"},
    "空调": {"stockOrg": "MI_AIRCONDITION", "purchaseOrg": "1131"},
    "电视": {"stockOrg": "MI_TV", "purchaseOrg": "1111"},
}


def extract_intent(text: str = "", image: str | None = None, sop: str | None = None) -> StepResult:
    sources = []
    combined = text or ""
    if sop:
        sop_path = Path(sop)
        if sop_path.exists():
            combined += "\n" + sop_path.read_text(encoding="utf-8", errors="ignore")
            sources.append(str(sop_path))
    if image:
        sources.append(image)
        combined += f"\n[image:{Path(image).name}]"

    intent: dict[str, object] = {"sourceType": "text"}
    if image and text:
        intent["sourceType"] = "image+text"
    elif image:
        intent["sourceType"] = "image"
    elif sop:
        intent["sourceType"] = "sop"

    for order_type in ORDER_TYPES:
        if order_type in combined.upper():
            intent["orderType"] = order_type
            break

    for name, mapping in PURCHASE_ORG_MAP.items():
        if name in combined:
            intent["purchaseOrgCN"] = name
            intent.update(mapping)
            break

    material_matches = re.findall(r"(?:物料|material)[^\w]*(\w{6,})", combined, flags=re.IGNORECASE)
    if material_matches:
        intent["materials"] = {f"materialCode{index}": value for index, value in enumerate(material_matches[:3], start=1)}

    supplier_match = re.search(r"(?:供应商|supplier)[^\w]*(\w{4,})", combined, flags=re.IGNORECASE)
    if supplier_match:
        intent["supplierCode"] = supplier_match.group(1)

    project_match = re.search(r"(?:项目|project)[^\w]*([\w\-]{4,})", combined, flags=re.IGNORECASE)
    if project_match:
        intent["projectCode"] = project_match.group(1)

    missing = [field for field in ["orderType", "purchaseOrg", "supplierCode", "materials", "projectCode"] if field not in intent]
    result = StepResult(
        name="vision_extract",
        status="SUCCESS" if len(missing) < 5 else "PARTIAL",
        detail="已提取造数意图，缺失字段需继续追问" if missing else "已提取完整造数意图",
        data={"intent": intent, "missingFields": missing, "sources": sources},
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="从文本/SOP/截图线索提取造数参数")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--text", default="")
    parser.add_argument("--image")
    parser.add_argument("--sop")
    args = parser.parse_args()

    result = extract_intent(args.text, args.image, args.sop)
    write_json(Path(args.run_dir) / "intent.json", result.to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
