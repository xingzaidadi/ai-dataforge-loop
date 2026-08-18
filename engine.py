#!/usr/bin/env python3
"""
AI 数据智造闭环引擎 — 通用编排引擎（精简入口）

用法：
    python engine.py <config.yaml> --输入参数 值

示例：
    python engine.py configs/znb-prpo.yaml \
        --stockOrg MI_IOT --purchaseOrg 2120 \
        --supplierCode SUPPLIER_DEMO \
        --materials '{"materialCode1":"MAT_DEMO_B"}' \
        --projectCode PROJECT_DEMO \
        --shipLocCode LOC_DEMO

通知方式：
    --notify feishu   每步发飞书卡片（零子进程，urllib直调）
    --notify stdout   纯终端输出（默认）
    --chat-id ID      飞书接收人 open_id（默认读 FEISHU_SENDER_OPEN_ID）
"""

import json
import os
import sys
import time
import argparse
from pathlib import Path

# Windows 控制台默认 GBK，打印 emoji/中文会 UnicodeEncodeError —— 强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        for _line in _env_path.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())

from lib import MifyClient, FlowEngine, load_config
from lib.config import load_mify_config

# ── 步骤元数据（用于飞书卡片展示）──────────────────────
STEP_META = {
    "get_cookie":       ("获取Cookie", "准备阶段"),
    "get_materials":    ("渲染物料模板", "准备阶段"),
    "fetch_materials":  ("查询物料元数据", "准备阶段"),
    "filter_materials": ("过滤匹配物料", "准备阶段"),
    "check_asl":        ("ASL供应商校验", "准备阶段"),
    "build_pr":         ("拼PR请求体", "PR创建"),
    "create_pr":        ("创建PR", "PR创建"),
    "check_pr":         ("检查PR", "PR创建"),
    "query_pr_info":    ("查询PR信息", "审批阶段"),
    "approve_pr":       ("PR审批", "审批阶段"),
    "query_items":      ("查询PR物料行", "PO创建"),
    "query_contract":   ("查询合同", "PO创建"),
    "build_prpo":       ("拼PR-PO请求体", "PO创建"),
    "pr_to_po":         ("PR转PO", "PO创建"),
    "check_po":         ("检查PO", "PO创建"),
    "query_po_info":    ("查询PO信息", "ERP推送"),
    "approve_po":       ("PO审批", "ERP推送"),
    "query_erp":        ("查询ERP单号", "ERP推送"),
    "check_erp":        ("检查ERP", "ERP推送"),
    "repush_erp":       ("重新推送ERP", "ERP推送"),
}

TOTAL_STEPS = 20


def make_feishu_notifier(mify: MifyClient, chat_id: str):
    """创建飞书卡片通知回调（零子进程）"""
    step_seq = [0]  # mutable counter

    def _find_seq(step_id: str) -> int:
        """查找步骤序号"""
        for i, (sid, _, _) in enumerate(STEP_META.items()):
            if sid == step_id:
                return i + 1
        return 0

    def _send(title: str, content: str, color: str):
        mify.send_feishu_card(chat_id, title, content, color)

    def notify(step_id: str, status: str, detail: str = ""):
        seq = _find_seq(step_id)
        name, phase = STEP_META.get(step_id, (step_id, "未知阶段"))

        if status == "start":
            step_seq[0] = seq
            title = f"🔄 [{seq}/{TOTAL_STEPS}] {name}"
            content = f"**阶段**: {phase}\n**状态**: 执行中..."
            _send(title, content, "blue")

        elif status == "done":
            title = f"✅ [{seq}/{TOTAL_STEPS}] {name}"
            content = f"**阶段**: {phase}\n**状态**: 完成\n**耗时**: {detail}"
            _send(title, content, "green")

        elif status == "error":
            title = f"❌ [{seq}/{TOTAL_STEPS}] {name}"
            content = f"**阶段**: {phase}\n**状态**: 失败\n**错误**: {detail}"
            _send(title, content, "red")

    return notify


def make_stdout_notifier():
    """创建终端输出通知回调（默认行为，保持原有 print）"""
    def notify(step_id: str, status: str, detail: str = ""):
        pass  # print 已在 flow.py 内部处理，这里不重复
    return notify


def main():
    parser = argparse.ArgumentParser(description="AI 数据智造闭环引擎 — 通用编排引擎")
    parser.add_argument("config", help="流程配置文件 (YAML)")
    parser.add_argument("--endpoint", default=None, help="mify API 端点")
    parser.add_argument("--token", default=None, help="mify API Token")
    parser.add_argument("--user", default=None, help="mify 用户名")
    parser.add_argument("--save-state", action="store_true", help="启用状态快照（支持中断恢复）")
    parser.add_argument("--notify", choices=["feishu", "stdout"], default="stdout",
                        help="通知方式: feishu=飞书卡片, stdout=终端输出(默认)")
    parser.add_argument("--chat-id", default=None,
                        help="飞书接收人 open_id（默认读 FEISHU_SENDER_OPEN_ID）")

    args, unknown = parser.parse_known_args()

    config = load_config(args.config)
    mify_conf = load_mify_config()

    endpoint = args.endpoint or mify_conf.get("endpoint", "")
    token = args.token or mify_conf.get("token", "")
    user = args.user or mify_conf.get("user", "ou_0f523a90cdfbb1cc84ccf67ba3fcf7ef")
    sql_token = mify_conf.get("sql_token", "")
    sql_workflow_id = mify_conf.get("sql_workflow_id", "")
    http_workflow_id = mify_conf.get("workflow_id", "")

    # 解析 --key value 参数
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
                except json.JSONDecodeError as e:
                    print(f"  ⚠️ 字段 {field_name} example 解析失败: {e}")
            inputs[field_name] = val

    print(f"🏭 AI 数据智造闭环引擎")
    print(f"📋 流程: {config['name']}")
    print(f"📦 输入: {json.dumps(inputs, ensure_ascii=False, indent=2)}")

    # 初始化
    mify = MifyClient(endpoint, token, user, sql_workflow_id,
                      http_workflow_id=http_workflow_id,
                      sql_token=sql_token)

    # 构建通知回调
    if args.notify == "feishu":
        chat_id = args.chat_id or os.environ.get("FEISHU_SENDER_OPEN_ID", "")
        if not chat_id:
            print("❌ --notify feishu 需要 --chat-id 或 FEISHU_SENDER_OPEN_ID")
            return
        notifier = make_feishu_notifier(mify, chat_id)
        # 启动卡片
        mify.send_feishu_card(
            chat_id,
            "🏭 造数工厂 · 开始执行",
            f"📦 供应商: {inputs.get('supplierCode', '?')}\n"
            f"📦 物料: {list(inputs.get('materials', {}).values())}\n\n"
            f"🚀 共 {TOTAL_STEPS} 步，逐步执行中...",
            "blue",
        )
    else:
        notifier = make_stdout_notifier()

    engine = FlowEngine(config, inputs, mify, progress_callback=notifier)

    # 获取 cookie
    cookie_url = config.get("config", {}).get("cookie_url")
    if cookie_url:
        print("\n📌 获取 Cookie...")
        engine.cookie = mify.get_cookie(cookie_url)
        if engine.cookie:
            print(f"  ✅ Cookie 获取成功 (长度: {len(engine.cookie)})")
        else:
            print(f"  ❌ Cookie 获取失败")
            return

    t0 = time.time()
    engine.run(save_state=args.save_state)
    elapsed = time.time() - t0

    # 完成卡片
    if args.notify == "feishu":
        mify.send_feishu_card(
            chat_id,
            "🎯 造数完成",
            f"⏱ 总耗时: {elapsed:.1f}s\n"
            f"✅ 所有步骤执行完毕",
            "green",
        )


if __name__ == "__main__":
    main()
