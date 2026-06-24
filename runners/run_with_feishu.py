#!/usr/bin/env python3
"""
造数执行器 — 带飞书实时进度推送
用法: python runners/run_with_feishu.py configs/znb-prpo.yaml --stockOrg MI_IOT ...
"""
import json
import sys
import time
import argparse
from pathlib import Path

_venv = Path(__file__).parent.parent / '.venv'
if _venv.exists():
    sys.path.insert(0, str(_venv))

try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent / '.env'
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.client import MifyClient
from lib.flow import FlowEngine
from lib.config import load_config, load_mify_config

STEP_LABELS = {
    "get_cookie": "🍪 获取Cookie",
    "get_materials": "📦 渲染物料模板",
    "fetch_materials": "🔍 查询物料信息",
    "filter_materials": "🔍 过滤物料",
    "check_asl": "✅ ASL校验",
    "build_pr": "📝 渲染PR模板",
    "create_pr": "📤 创建PR",
    "query_pr_info": "🗄️ 查询PR号",
    "approve_pr": "✅ PR审批",
    "query_items": "🗄️ 查询PR物料行",
    "query_contract": "🗄️ 查询合同",
    "pr_to_po": "📤 PR转PO",
    "approve_po": "✅ PO审批",
    "check_po": "🔀 PO检查",
    "query_erp": "🗄️ 查询ERP单号",
    "repush_erp": "📤 重推ERP",
}

PHASES = {
    "get_cookie": ("阶段1", "准备阶段"),
    "fetch_materials": ("阶段1", "准备阶段"),
    "build_pr": ("阶段1", "准备阶段"),
    "create_pr": ("阶段1", "准备阶段"),
    "query_pr_info": ("阶段2", "审批阶段"),
    "approve_pr": ("阶段2", "审批阶段"),
    "query_items": ("阶段2", "审批阶段"),
    "query_contract": ("阶段2", "审批阶段"),
    "pr_to_po": ("阶段2", "审批阶段"),
    "approve_po": ("阶段3", "收尾阶段"),
    "query_erp": ("阶段3", "收尾阶段"),
    "repush_erp": ("阶段3", "收尾阶段"),
}

_step_times = {}
_current_phase = ""


def _progress_callback(step_id, status, detail=""):
    global _current_phase
    label = STEP_LABELS.get(step_id, step_id)
    phase_info = PHASES.get(step_id, ("", ""))
    icon = {"start": "⏳", "done": "✅", "error": "❌"}.get(status, "ℹ️")

    if status == "start":
        _step_times[step_id] = time.time()
        elapsed_str = ""
    elif step_id in _step_times:
        elapsed = time.time() - _step_times[step_id]
        elapsed_str = f" ({elapsed:.1f}s)"
    else:
        elapsed_str = ""

    phase_label = phase_info[0] if phase_info[0] else ""
    if phase_label and phase_label != _current_phase:
        _current_phase = phase_label
        phase_name = phase_info[1]
        print(f"__PROGRESS__:━━ {phase_label} {phase_name} ━━", flush=True)

    msg = f"__PROGRESS__:{icon} {label}{elapsed_str}"
    if detail and status != "start":
        msg += f" -> {detail}"
    print(msg, flush=True)


def main():
    parser = argparse.ArgumentParser(description="Mify 造数工厂 — 带进度推送")
    parser.add_argument("config", help="流程配置文件 (YAML)")
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--user", default=None)
    parser.add_argument("--save-state", action="store_true")

    args, unknown = parser.parse_known_args()
    config = load_config(args.config)
    mify_conf = load_mify_config()

    endpoint = args.endpoint or mify_conf.get("endpoint", "")
    token = args.token or mify_conf.get("token", "")
    user = args.user or mify_conf.get("user", "skill-runner")
    sql_token = mify_conf.get("sql_token", "")
    sql_workflow_id = mify_conf.get("sql_workflow_id", "")
    http_workflow_id = mify_conf.get("workflow_id", "")

    inputs = {}
    i = 0
    while i < len(unknown):
        key = unknown[i].lstrip("-")
        if i + 1 < len(unknown) and not unknown[i + 1].startswith("-"):
            val = unknown[i + 1]
            try:
                val = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
            inputs[key] = val
            i += 2
        else:
            inputs[key] = True
            i += 1

    for field_name, field_def in config.get("inputs", {}).items():
        if field_name not in inputs and "example" in field_def:
            val = field_def["example"]
            if field_def.get("type") == "object":
                try:
                    val = json.loads(val)
                except json.JSONDecodeError:
                    pass
            inputs[field_name] = val

    print(f"__PROGRESS__:造数工厂启动", flush=True)
    print(f"__PROGRESS__:流程: {config['name']}", flush=True)

    stock_org = inputs.get("stockOrg", "")
    supplier = inputs.get("supplierCode", "")
    materials = inputs.get("materials", {})
    if isinstance(materials, dict):
        mat_list = list(materials.values())
    else:
        mat_list = [str(materials)]
    print(f"__PROGRESS__:{stock_org} | 供应商{supplier} | 物料{', '.join(mat_list)}", flush=True)

    mify = MifyClient(endpoint, token, user, sql_workflow_id,
                      http_workflow_id=http_workflow_id,
                      sql_token=sql_token)
    engine = FlowEngine(config, inputs, mify, progress_callback=_progress_callback)

    cookie_url = config.get("config", {}).get("cookie_url")
    if cookie_url:
        print(f"__PROGRESS__:[...] 获取Cookie", flush=True)
        engine.cookie = mify.get_cookie(cookie_url)
        if engine.cookie:
            print(f"__PROGRESS__:[OK] Cookie就绪 ({len(engine.cookie)}字符)", flush=True)
        else:
            print(f"__PROGRESS__:[FAIL] Cookie获取失败", flush=True)
            return

    t_total = time.time()
    engine.run(save_state=args.save_state)
    total_elapsed = time.time() - t_total
    print(f"__PROGRESS__:全部完成! 总耗时 {total_elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    main()
