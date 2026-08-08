#!/usr/bin/env python3
"""SRM 侧 ASN 承接 — 后置发货通知执行器（阶段3）。

用法（poNo 等业务参数是 positional key=value，只有 --config/--dry-run/--run-dir 是 flag）：
    python tools/srm_asn_create.py --config configs/srm-asn-create.yaml poNo=4500189594 supplierCode=100171
    python tools/srm_asn_create.py --config configs/srm-asn-create.yaml --dry-run poNo=4500189594 supplierCode=100171

在闭环流程中由 closed_loop_runner.py 调用（阶段2 PO Ready Gate 通过后承接）。

职责（对标 tools/srm_price_clean.py）：
    ① 校验参数（poNo 必填；大货类别 pullCommand 条件必填）
    ② 依据 PO 信息 / taskType 解析命中的 datacube 场景（SCENE_MAP）
    ③ 调用 configs/srm-asn-create.yaml 执行建 ASN
    ④ 解析 ASN 单号，写入 asn-result.json
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


# ASN 承接必填字段
_REQUIRED_FIELDS = [
    ("poNo", "采购订单号"),
]

_OPTIONAL_DEFAULTS = {
    "warehouseId": "420",
}

# 供应商编码 → 承接类别（对照 ASN 机器人的 GAOTONG/MTK/TI 硬编码清单）
_SUPPLIER_CATEGORY = {
    "100171": "GAOTONG", "124899": "GAOTONG",
    "100227": "MTK", "101550": "MTK", "100015": "MTK", "101408": "MTK",
    "126929": "TI", "133041": "TI",
}

# 三大 EDI 类别（建单后需外部凭证号回查真实 ASN）
_EDI_CATEGORIES = {"GAOTONG", "TI", "MTK"}

# 场景映射：category → [1行, 2行, 3行] 的 (sceneId, sceneName)
# sceneId/sceneName 逐一核对自 ASN 机器人 YAML 中 scene/execute 节点的真实请求体
# （见 templates/asn-scene-skeletons.json，由 _extract_scenes.py 提取）。
# 顺序严格为行数升序 [1行, 2行, 3行]；成品(CHENGPIN/JC)最多 2 行；TI 无 3 行场景。
# ⚠️ 历史版本此表 1行/3行 多处颠倒（如 PO 单行误配 376=3行场景），
#    导致单行 PO 发出 3 行 scene、空行触发 SAP 500 CX_SY_ITAB_LINE_NOT_FOUND；已按真值修正。
_SCENE_MAP: dict[str, list[tuple[int, str]]] = {
    "GAOTONG":  [(369, "高通创建ASN_1行"), (339, "高通创建ASN_2行"), (370, "高通创建ASN_3行")],
    "TI":       [(372, "TI创建ASN_1行"),   (340, "TI创建ASN_2行")],
    "MTK":      [(373, "MTK创建ASN_1行"),  (338, "MTK创建ASN_2行"),  (374, "MTK创建ASN_3行")],
    "PO":       [(375, "SRM-根据PO创建ASN-仅限独立需求)_1行"), (341, "SRM-根据PO创建ASN-仅限独立需求)_2行"), (376, "SRM-根据PO创建ASN-仅限独立需求)_3行")],
    "CIN":      [(378, "SRM-根据拉料指令创建ASN-仅限大货ZNB材料_1行"), (342, "SRM-根据拉料指令创建ASN-仅限大货ZNB材料_2行"), (377, "SRM-根据拉料指令创建ASN-仅限大货ZNB材料_3行")],
    "CHENGPIN": [(384, "SRM-成品(ZPJ\\ZWW)创建ASN_1行"), (385, "SRM-成品(ZPJ\\ZWW)创建ASN_2行")],
    "JC":       [(382, "SRM-成品(ZJC)创建ASN_1行"), (383, "SRM-成品(ZJC)创建ASN_2行")],
}

# 真实 scene/execute 请求体骨架（按 sceneId）——含各场景特有的内嵌 API 编排，
# body 中 __PO__ 为 ERP 采购单号占位，运行时由 build_scene_body_from_skeleton 替换。
_SKELETON_PATH = ROOT / "templates" / "asn-scene-skeletons.json"


def _load_skeletons() -> dict[str, Any]:
    try:
        with open(_SKELETON_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def build_scene_body_from_skeleton(scene_id: Any, po_no: str) -> str | None:
    """按 sceneId 取真实骨架并注入 ERP PO，返回可直接 POST 的 JSON 字符串。

    未找到骨架时返回 None（调用方回退到 Jinja 模板或阻断）。
    """
    if scene_id in (None, ""):
        return None
    skeletons = _load_skeletons()
    entry = skeletons.get(str(scene_id))
    if not entry:
        return None
    body = entry.get("body", "")
    if not body:
        return None
    return body.replace("__PO__", str(po_no or ""))


def _validate_inputs(params: dict[str, Any]) -> list[str]:
    """校验必填字段，返回错误列表（空 = 通过）。"""
    errors = []
    for field, label in _REQUIRED_FIELDS:
        val = params.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"缺少必填字段: {field} ({label})")
    # 条件必填：大货(CIN)类别必须带拉料指令
    if params.get("asnCategory") == "CIN":
        pull = params.get("pullCommand")
        if pull is None or (isinstance(pull, str) and not pull.strip()):
            errors.append("大货(CIN)承接必须提供 pullCommand(拉料指令)")
    return errors


def _fill_defaults(params: dict[str, Any]) -> dict[str, Any]:
    """填充可选字段默认值，不覆盖用户显式传入的值。"""
    filled = dict(params)
    for key, default in _OPTIONAL_DEFAULTS.items():
        if key not in filled or filled[key] is None or filled[key] == "":
            filled[key] = default
    return filled


def resolve_category(supplier_code: str | None, bsart: str | None,
                     pull_command: str | None, matkl: str | None) -> str:
    """依据 PO 信息推断承接类别（对齐 ASN 机器人 code 节点逻辑）。

    优先级：三大供应商编码 > 拉料指令(大货) > 成品(ZWW/ZPJ/ZDB+料号s/f) > 寄存(ZJC) > 独立需求(PO)。
    """
    # supplierCode 可能以 int 传入（parse_kv_pairs 会 json.loads），统一转字符串比对
    supplier_key = str(supplier_code).strip() if supplier_code not in (None, "") else ""
    if supplier_key and supplier_key in _SUPPLIER_CATEGORY:
        return _SUPPLIER_CATEGORY[supplier_key]
    if pull_command:
        return "CIN"
    if bsart in {"ZWW", "ZPJ", "ZDB"} and matkl and matkl[:1].lower() in {"s", "f"}:
        return "CHENGPIN"
    if bsart == "ZJC":
        return "JC"
    return "PO"


def resolve_scene(category: str, line_count: int) -> dict[str, Any]:
    """依据 类别 × 行数 命中 datacube 场景，返回 taskType/sceneId/sceneName。

    行数上限：成品(CHENGPIN/JC)最多 2 行，其余最多 3 行。
    未命中时返回占位场景（配置已预留、待接入），不谎报已支持。
    """
    scenes = _SCENE_MAP.get(category)
    if not scenes:
        return {
            "taskType": f"{category}_{line_count}",
            "sceneId": "",
            "sceneName": "",
            "resolved": False,
            "note": f"类别 {category} 场景未预置，配置已预留待接入",
        }
    max_line = len(scenes)
    idx = max(1, min(line_count, max_line))
    scene_id, scene_name = scenes[idx - 1]
    return {
        "taskType": f"{category}_{idx}",
        "sceneId": scene_id,
        "sceneName": scene_name,
        "resolved": True,
    }


def _parse_asn_output(stdout: str) -> dict[str, Any]:
    """从 engine.py 的 stdout 中解析 ASN 执行结果（对标 srm_price_clean._parse_clean_output）。"""
    result: dict[str, Any] = {
        "steps_extracted": {},
        "final_status": "UNKNOWN",
        "errors": [],
        "asnNo": None,
        "raw_stdout": stdout[-3000:] if len(stdout) > 3000 else stdout,
    }
    for raw in stdout.strip().split("\n"):
        line = raw.strip()
        if line.startswith("📌"):
            parts = line[2:].split("=", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()
                result["steps_extracted"][key] = value
                if key in ("asn_no", "zasn_no") and value and value != "None":
                    result["asnNo"] = value
        elif line.startswith("✅ 流程执行完毕"):
            result["final_status"] = "SUCCESS"
        elif line.startswith("❌ 步骤"):
            result["final_status"] = "FAILED"
            result["errors"].append(line)
        elif "❌" in line and ("错误" in line or "失败" in line):
            result["errors"].append(line)
    return result


def run_srm_asn_create(
    config: str,
    params: dict[str, Any],
    run_dir: Path,
    dry_run: bool = False,
) -> StepResult:
    """执行 SRM 侧 ASN 承接。

    流程：校验输入 → 解析场景 → 执行建 ASN → 解析 ASN 单号
    返回 StepResult，status 为 SUCCESS / FAILED / SKIPPED。
    """
    scene_note = None
    category_degraded = False
    # ── 阶段 1：解析承接类别与场景（若上游未注入）──
    if not params.get("asnCategory"):
        has_meta = any(params.get(k) not in (None, "") for k in ("supplierCode", "bsart", "matkl", "pullCommand"))
        params["asnCategory"] = resolve_category(
            supplier_code=params.get("supplierCode"),
            bsart=params.get("bsart"),
            pull_command=params.get("pullCommand"),
            matkl=params.get("matkl"),
        )
        # 诚实标记：无任何 PO 元数据（只给 poNo）时，分类必然落到 PO 兜底，
        # 这不是"确认为独立需求"，而是"缺元数据无法分类"——需显式告知，避免把高通/TI/成品 PO 误当独立需求。
        if not has_meta and params["asnCategory"] == "PO":
            category_degraded = True
    if not params.get("taskType") or not params.get("sceneId"):
        try:
            line_count = int(params.get("lineCount", 1))
        except (TypeError, ValueError):
            line_count = 1
        scene = resolve_scene(params["asnCategory"], line_count)
        params.setdefault("taskType", scene["taskType"])
        if scene.get("sceneId") != "":
            params.setdefault("sceneId", scene["sceneId"])
            params.setdefault("sceneName", scene["sceneName"])
        scene_note = scene

    # ── 阶段 1.5：未命中场景阻断 ──
    # resolve_scene 未命中（resolved=False）且用户未显式传入 sceneId 时，
    # 直接阻断，不带空 sceneId 进入真实执行——诚实预留，不谎报已支持。
    if not params.get("sceneId"):
        task_type = params.get("taskType", params.get("asnCategory", ""))
        detail = f"场景未接入：类别×行数组合 {task_type} 未预置 sceneId，配置已预留待接入，不进入真实执行"
        result = StepResult(
            name="srm_asn_create",
            status="BLOCKED",
            detail=detail,
            data={
                "resolved": False,
                "taskType": task_type,
                "note": (scene_note or {}).get("note", detail),
                "params": params,
            },
        )
        write_json(run_dir / "asn-result.json", result.to_dict())
        print(f"  🚧 {detail}")
        return result

    # ── 阶段 1.6：注入真实 scene 骨架（按 sceneId 取内嵌 API 编排，替换 PO）──
    # 未找到骨架不阻断——模板会回退到最小结构（仅够发出请求，真建单能力有限）。
    if not params.get("sceneBody"):
        skeleton_body = build_scene_body_from_skeleton(params.get("sceneId"), params.get("poNo", ""))
        if skeleton_body:
            params["sceneBody"] = skeleton_body

    # ── 阶段 2：输入校验 ──
    errors = _validate_inputs(params)
    if errors:
        detail = "输入校验失败: " + "; ".join(errors)
        result = StepResult(
            name="srm_asn_create",
            status="FAILED",
            detail=detail,
            data={"errors": errors, "params": params},
        )
        write_json(run_dir / "asn-result.json", result.to_dict())
        print(f"  ❌ {detail}")
        return result

    filled_params = _fill_defaults(params)

    # ── 阶段 3：构建命令 ──
    command = [sys.executable, str(ROOT / "engine.py"), config]
    for key, value in filled_params.items():
        command.extend([
            f"--{key}",
            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False),
        ])

    category_warning = None
    if category_degraded:
        category_warning = (
            "承接类别在缺少 PO 元数据（supplierCode/bsart/matkl）时降级到 PO 兜底，"
            "非确认的独立需求——如为高通/TI/MTK/成品 PO，请显式传入 supplierCode 或 asnCategory 以正确分类"
        )
    business = {
        "poNo": filled_params.get("poNo"),
        "asnCategory": filled_params.get("asnCategory"),
        "asnScene": filled_params.get("sceneName") or filled_params.get("taskType"),
        "taskType": filled_params.get("taskType"),
        "pullCommand": filled_params.get("pullCommand"),
        "warehouseId": filled_params.get("warehouseId"),
        "categoryDegraded": category_degraded,
    }

    if dry_run:
        result = StepResult(
            name="srm_asn_create",
            status="SKIPPED",
            detail="dry-run 模式未真实执行 SRM ASN 承接",
            data={
                "command": command,
                "filled_params": filled_params,
                "businessData": {**business, "zasnNo": "ASN-DRYRUN-PLACEHOLDER"},
                "warnings": [category_warning] if category_warning else None,
            },
        )
        write_json(run_dir / "asn-result.json", result.to_dict())
        if category_warning:
            print(f"  ⚠️ {category_warning}")
        print(f"  ⏭️ dry-run: 命中场景 {business['asnScene']} (taskType={business['taskType']})")
        return result

    # ── 阶段 4：执行建 ASN ──
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=300,  # 5 分钟：场景编排含轮询
        )
        parsed = _parse_asn_output(completed.stdout)
        asn_no = parsed.get("asnNo")

        if completed.returncode != 0:
            status = "FAILED"
            detail = f"ASN 承接失败 (rc={completed.returncode})"
        elif parsed.get("errors"):
            status = "FAILED"
            detail = f"ASN 承接出错: {'; '.join(parsed['errors'][:3])}"
        elif not asn_no:
            status = "FAILED"
            detail = "ASN 承接完成但未取到 ASN 单号（接单失败/ASN创建失败）"
        else:
            status = "SUCCESS"
            detail = f"ASN 承接完成，单号 {asn_no}"

        result = StepResult(
            name="srm_asn_create",
            status=status,
            detail=detail,
            data={
                "returncode": completed.returncode,
                "command": command,
                "businessData": {**business, "zasnNo": asn_no},
                "stdout": completed.stdout[-2000:] if len(completed.stdout) > 2000 else completed.stdout,
                "stderr": completed.stderr[-1000:] if len(completed.stderr) > 1000 else completed.stderr,
                "parsed": parsed,
            },
        )
    except subprocess.TimeoutExpired:
        result = StepResult(
            name="srm_asn_create",
            status="FAILED",
            detail="SRM ASN 承接执行超时（5 分钟上限）",
            data={"command": command, "timeout": 300},
        )
    write_json(run_dir / "asn-result.json", result.to_dict())

    icon = "✅" if result.status == "SUCCESS" else "❌"
    print(f"  {icon} {result.detail}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="SRM 侧 ASN 承接（独立运行）")
    parser.add_argument("--config", default="configs/srm-asn-create.yaml", help="ASN 承接配置")
    parser.add_argument("--run-dir", default=".", help="输出目录")
    parser.add_argument("--dry-run", action="store_true", help="只生成命令不执行")
    parser.add_argument("params", nargs="*", help="key=value 参数")
    args = parser.parse_args()

    result = run_srm_asn_create(
        config=args.config,
        params=parse_kv_pairs(args.params),
        run_dir=Path(args.run_dir),
        dry_run=args.dry_run,
    )
    print(result.detail)
    return 0 if result.status in {"SUCCESS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
