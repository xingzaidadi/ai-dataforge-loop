#!/usr/bin/env python3
"""SRM 侧 拉料指令创建&审批 — 大货 ASN 前置（阶段2.5）。

用法（业务参数是 positional key=value，只有 --config/--dry-run/--run-dir 是 flag）：
    python tools/srm_pull_command.py --config configs/srm-pull-command.yaml \
        stockOrg=MI_PHONE purchaseOrg=1110 supplierCode=100171 \
        materialCode1=22CK1AC225AC shipLocCode=L16-CN
    python tools/srm_pull_command.py --config configs/srm-pull-command.yaml --dry-run ...

在闭环流程中由 closed_loop_runner.py 调用（阶段2 PO Ready Gate 通过后、阶段3 ASN 前）。

职责（对标 tools/srm_asn_create.py）：
    ① 校验参数（stockOrg/purchaseOrg/supplierCode/materialCode1/shipLocCode 必填）
    ② 依据 预占模式/电视采组 解析命中的 datacube 场景（199 无预占/396 95FPO/398 电视）
    ③ 注入真实场景骨架（cookie→创建→一键审批 内嵌 API 编排，占位符替换）
    ④ 调用 configs/srm-pull-command.yaml 执行建拉料指令
    ⑤ 解析 commandCode(2608... 16位)，写入 pull-command-result.json；供阶段3 ASN 当 pullCommand
       注意：commandCode 不在「创建」响应里，取自「拉料指令列表-审批中」步骤 $.data.list[0].commandCode
"""

from __future__ import annotations

import argparse
import json
import re
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


# 拉料指令创建必填字段（对齐「创建拉料指令」mify 工作流 start 变量 + 参数提取器2）
_REQUIRED_FIELDS = [
    ("stockOrg", "库存组织"),
    ("purchaseOrg", "采购组织"),
    ("supplierCode", "供应商编码"),
    ("materialCode1", "物料编码1"),
    ("shipLocCode", "代工厂/发货地点"),
]

# 采组含此串则不走拉料指令（对齐「原材料-PRPO拉料」条件分支2：purchaseOrg contains 111K）
_SKIP_PURCHASE_ORG_MARK = "111K"

# 场景骨架（按 sceneId）——含各场景特有的 cookie→创建→审批 内嵌 API 编排，
# body 中 __<name>__ 为占位符，运行时由 build_scene_body_from_skeleton 替换。
_SKELETON_PATH = ROOT / "templates" / "pull-command-skeletons.json"


def _load_skeletons() -> dict[str, Any]:
    try:
        with open(_SKELETON_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_scene(params: dict[str, Any]) -> dict[str, Any]:
    """依据 预占模式 / 电视采组 命中 datacube 拉料指令场景。

    对齐「创建拉料指令」mify 工作流分支：
    - 采组含「电视」→ 电视场景 (sceneId=398, taskId=414)
    - occupyMode/预占模式 == 95FPO → 95FPO 场景 (sceneId=396, taskId=411)
    - 其余（无预占）→ 无预占场景 (sceneId=199, taskId=136)  ← 最常用

    返回 sceneId/sceneName/taskId/resolved。
    """
    purchase_org_cn = str(params.get("purchaseOrgCN") or params.get("purchaseOrg") or "")
    occupy_mode = str(params.get("occupyMode") or params.get("occupyModeLabel") or "").upper()

    if "电视" in purchase_org_cn:
        return {"sceneId": 398, "sceneName": "拉料指令创建&审批-无预占模式-电视",
                "taskId": 414, "resolved": True, "variant": "TV"}
    if "95FPO" in occupy_mode:
        return {"sceneId": 396, "sceneName": "拉料指令创建-预占95FPO",
                "taskId": 411, "resolved": True, "variant": "95FPO"}
    return {"sceneId": 199, "sceneName": "拉料指令创建&审批-无预占模式",
            "taskId": 136, "resolved": True, "variant": "NO_OCCUPY"}


def _build_field_values(fields: list[str], params: dict[str, Any],
                        execute_person: str) -> dict[str, str]:
    """依据骨架声明的占位符字段，组装 {占位符字段: 值}。

    占位符来自各场景 create 节点的 apiVariables 名，直接从 params 取同名值；
    EXECUTE_PERSON 取 config.execute_person（默认 liusixing）。
    materialCode2 缺省填空串（单物料拉料指令允许第二料为空）。
    """
    values: dict[str, str] = {}
    for f in fields:
        if f == "EXECUTE_PERSON":
            values[f] = execute_person or "liusixing"
        elif f == "destLocCode":
            # 95FPO：目的地缺省回退到 shipLocCode（对齐工作流 destLocCode 默认取 shipLocCode）
            values[f] = str(params.get("destLocCode") or params.get("shipLocCode") or "")
        else:
            v = params.get(f)
            values[f] = str(v) if v not in (None, "") else ""
    return values


def build_scene_body_from_skeleton(scene_id: Any, params: dict[str, Any],
                                   execute_person: str) -> str | None:
    """按 sceneId 取真实骨架并注入所有占位符，返回可直接 POST 的 JSON 字符串。

    未找到骨架时返回 None（调用方回退模板最小结构）。
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
    fields = entry.get("fields", []) or []
    for name, val in _build_field_values(fields, params, execute_person).items():
        body = body.replace(f"__{name}__", val)
    return body


def _validate_inputs(params: dict[str, Any]) -> list[str]:
    """校验必填字段，返回错误列表（空 = 通过）。"""
    errors = []
    for field, label in _REQUIRED_FIELDS:
        val = params.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"缺少必填字段: {field} ({label})")
    # 95FPO / 电视 需要 projectCode（对齐工作流业务规则）
    scene = resolve_scene(params)
    if scene["variant"] in ("95FPO", "TV") and not params.get("projectCode"):
        errors.append(f"{scene['variant']} 拉料指令必须提供 projectCode(项目编码)")
    return errors


def should_skip(params: dict[str, Any]) -> tuple[bool, str]:
    """判断该采组是否需要拉料指令（对齐 111K 分支）。

    返回 (skip, reason)。purchaseOrg 含 111K → 跳过（该采组 ASN 不经拉料指令）。
    """
    purchase_org = str(params.get("purchaseOrg") or "")
    if _SKIP_PURCHASE_ORG_MARK in purchase_org:
        return True, f"采购组织 {purchase_org} 含 {_SKIP_PURCHASE_ORG_MARK}，该采组 ASN 不经拉料指令，跳过"
    return False, ""


def _parse_pull_output(stdout: str) -> dict[str, Any]:
    """从 engine.py 的 stdout 中解析拉料指令执行结果（对标 srm_asn_create._parse_asn_output）。"""
    result: dict[str, Any] = {
        "steps_extracted": {},
        "final_status": "UNKNOWN",
        "errors": [],
        "commandCode": None,
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
                if key in ("command_code", "commandCode") and value and value != "None":
                    result["commandCode"] = value
        elif line.startswith("✅ 流程执行完毕") or line.startswith("✅ SRM 侧 拉料指令创建完成"):
            result["final_status"] = "SUCCESS"
        elif line.startswith("❌ 步骤"):
            result["final_status"] = "FAILED"
            result["errors"].append(line)
        elif "❌" in line and ("错误" in line or "失败" in line):
            result["errors"].append(line)
    return result


def _extract_command_code_from_log(parsed: dict[str, Any]) -> str | None:
    """兜底：从 scene_log/执行响应文本里正则捞 commandCode。

    真实链路(taskId 411)证实：commandCode 不在「创建」响应里，而在「拉料指令列表-审批中」
    步骤响应 $.data.list[0].commandCode，格式为 2608 开头的 16 位纯数字（如 2608110000000006）。
    优先取结构化提取的 command_code；否则从日志文本按真实格式兜底。
    """
    if parsed.get("commandCode"):
        return parsed["commandCode"]
    # 扫描所有步骤提取值（execute_result / scene_log 均可能承载列表步骤响应）
    extracted = parsed.get("steps_extracted", {}) or {}
    text = " ".join(
        str(v) for v in extracted.values() if v not in (None, "", "None", "{}")
    )
    if not text.strip():
        return None
    # 首选：显式 JSON 字段 "commandCode":"..."
    m = re.search(r'"commandCode"\s*:\s*"?(\d{12,20})"?', text)
    if m:
        return m.group(1)
    # 兜底：真实格式 2608 开头 16 位；再退回历史 4500... 10 位
    m = re.search(r"(?<!\d)(2608\d{12})(?!\d)", text)
    if m:
        return m.group(1)
    m = re.search(r"(?<!\d)(4500\d{6})(?!\d)", text)
    return m.group(1) if m else None


def run_srm_pull_command(
    config: str,
    params: dict[str, Any],
    run_dir: Path,
    dry_run: bool = False,
    execute_person: str = "",
) -> StepResult:
    """执行 SRM 侧 拉料指令创建&审批。

    流程：判是否需要 → 校验输入 → 解析场景 → 注入骨架 → 执行 → 解析 commandCode
    返回 StepResult，status 为 SUCCESS / FAILED / SKIPPED / BLOCKED。
    data.businessData.commandCode 供阶段3 ASN 当 pullCommand 消费。
    """
    # ── 阶段 0：采组豁免判定（111K 不走拉料指令）──
    skip, skip_reason = should_skip(params)
    if skip:
        result = StepResult(
            name="srm_pull_command",
            status="SKIPPED",
            detail=skip_reason,
            data={"skipped": True, "reason": skip_reason,
                  "businessData": {"commandCode": None}},
        )
        write_json(run_dir / "pull-command-result.json", result.to_dict())
        print(f"  ⏭️ {skip_reason}")
        return result

    # ── 阶段 1：解析场景（预占模式/电视）──
    scene = resolve_scene(params)
    params.setdefault("sceneId", scene["sceneId"])
    params.setdefault("sceneName", scene["sceneName"])
    params.setdefault("taskId", scene["taskId"])

    # ── 阶段 2：输入校验 ──
    errors = _validate_inputs(params)
    if errors:
        detail = "输入校验失败: " + "; ".join(errors)
        result = StepResult(
            name="srm_pull_command",
            status="FAILED",
            detail=detail,
            data={"errors": errors, "params": params,
                  "businessData": {"commandCode": None}},
        )
        write_json(run_dir / "pull-command-result.json", result.to_dict())
        print(f"  ❌ {detail}")
        return result

    # ── 阶段 3：注入真实场景骨架（cookie→创建→审批 内嵌编排，替换占位符）──
    if not params.get("sceneBody"):
        skeleton_body = build_scene_body_from_skeleton(
            params.get("sceneId"), params, execute_person,
        )
        if skeleton_body:
            residual = re.findall(r"__[A-Za-z0-9_]+__", skeleton_body)
            if residual:
                detail = (
                    f"场景 {params.get('sceneId')} 骨架仍有未填充占位符 {sorted(set(residual))}"
                    "——不带脏占位符进入真实执行"
                )
                result = StepResult(
                    name="srm_pull_command",
                    status="BLOCKED",
                    detail=detail,
                    data={"resolved": False, "residualPlaceholders": sorted(set(residual)),
                          "sceneId": params.get("sceneId"), "params": params,
                          "businessData": {"commandCode": None}},
                )
                write_json(run_dir / "pull-command-result.json", result.to_dict())
                print(f"  🚧 {detail}")
                return result
            params["sceneBody"] = skeleton_body

    business = {
        "stockOrg": params.get("stockOrg"),
        "purchaseOrg": params.get("purchaseOrg"),
        "supplierCode": params.get("supplierCode"),
        "materialCode1": params.get("materialCode1"),
        "shipLocCode": params.get("shipLocCode"),
        "pullScene": scene["sceneName"],
        "sceneId": scene["sceneId"],
        "variant": scene["variant"],
    }

    # ── 阶段 4：构建命令 ──
    command = [sys.executable, str(ROOT / "engine.py"), config]
    for key, value in params.items():
        command.extend([
            f"--{key}",
            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False),
        ])

    if dry_run:
        result = StepResult(
            name="srm_pull_command",
            status="SKIPPED",
            detail=f"dry-run 模式未真实执行；命中场景 {scene['sceneName']} (sceneId={scene['sceneId']})",
            data={
                "command": command,
                "businessData": {**business, "commandCode": "PULLCMD-DRYRUN-PLACEHOLDER"},
            },
        )
        write_json(run_dir / "pull-command-result.json", result.to_dict())
        print(f"  ⏭️ dry-run: 命中场景 {scene['sceneName']} (sceneId={scene['sceneId']})")
        return result

    # ── 阶段 5：执行建拉料指令 ──
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=300,  # 5 分钟：场景编排含轮询 + 一键审批
        )
        parsed = _parse_pull_output(completed.stdout)
        command_code = _extract_command_code_from_log(parsed)

        if completed.returncode != 0:
            status = "FAILED"
            detail = f"拉料指令创建失败 (rc={completed.returncode})"
        elif parsed.get("errors"):
            status = "FAILED"
            detail = f"拉料指令创建出错: {'; '.join(parsed['errors'][:3])}"
        elif not command_code:
            status = "FAILED"
            detail = "拉料指令创建完成但未取到 commandCode（接口丢响应体/审批未过）"
        else:
            status = "SUCCESS"
            detail = f"拉料指令创建完成，commandCode {command_code}"

        result = StepResult(
            name="srm_pull_command",
            status=status,
            detail=detail,
            data={
                "returncode": completed.returncode,
                "command": command,
                "businessData": {**business, "commandCode": command_code},
                "stdout": completed.stdout[-2000:] if len(completed.stdout) > 2000 else completed.stdout,
                "stderr": completed.stderr[-1000:] if len(completed.stderr) > 1000 else completed.stderr,
                "parsed": parsed,
            },
        )
    except subprocess.TimeoutExpired:
        result = StepResult(
            name="srm_pull_command",
            status="FAILED",
            detail="SRM 拉料指令创建执行超时（5 分钟上限）",
            data={"command": command, "timeout": 300,
                  "businessData": {"commandCode": None}},
        )
    write_json(run_dir / "pull-command-result.json", result.to_dict())

    icon = "✅" if result.status == "SUCCESS" else "❌"
    print(f"  {icon} {result.detail}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="SRM 侧 拉料指令创建（独立运行）")
    parser.add_argument("--config", default="configs/srm-pull-command.yaml", help="拉料指令配置")
    parser.add_argument("--run-dir", default=".", help="输出目录")
    parser.add_argument("--dry-run", action="store_true", help="只生成命令不执行")
    parser.add_argument("params", nargs="*", help="key=value 参数")
    args = parser.parse_args()

    result = run_srm_pull_command(
        config=args.config,
        params=parse_kv_pairs(args.params),
        run_dir=Path(args.run_dir),
        dry_run=args.dry_run,
    )
    print(result.detail)
    return 0 if result.status in {"SUCCESS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
