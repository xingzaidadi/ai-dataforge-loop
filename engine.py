#!/usr/bin/env python3
"""
Mify 造数工厂 — 通用编排引擎（精简入口）

用法：
    python engine.py <config.yaml> --输入参数 值

示例：
    python engine.py configs/znb-prpo.yaml \
        --stockOrg MI_IOT --purchaseOrg 2120 \
        --supplierCode 108062 \
        --materials '{"materialCode1":"1710301000006B"}' \
        --projectCode EcoOdmJdm20240708220947-EU \
        --shipLocCode 129797

新增造单场景只需：
    1. 写 configs/xxx.yaml（流程配置，支持 use 指令引用共享步骤）
    2. 写 templates/xxx.json.j2（模板，可选）
    3. 不用写 Python！
"""

import json
import sys
import argparse
from pathlib import Path

from lib import MifyClient, FlowEngine, load_config
from lib.config import load_mify_config


def main():
    parser = argparse.ArgumentParser(description="Mify 造数工厂 — 通用编排引擎")
    parser.add_argument("config", help="流程配置文件 (YAML)")
    parser.add_argument("--endpoint", default=None, help="mify API 端点")
    parser.add_argument("--token", default=None, help="mify API Token")
    parser.add_argument("--user", default=None, help="mify 用户名")
    parser.add_argument("--save-state", action="store_true", help="启用状态快照（支持中断恢复）")

    # 动态参数通过 **kwargs 捕获
    args, unknown = parser.parse_known_args()

    # 读取配置（自动展开 use 指令）
    config = load_config(args.config)

    # 从配置读取 mify 端点
    mify_conf = load_mify_config()

    endpoint = args.endpoint or mify_conf.get("endpoint", "")
    token = args.token or mify_conf.get("token", "")
    user = args.user or mify_conf.get("user", "skill-runner")
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
            # 尝试解析 JSON
            try:
                val = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
            inputs[key] = val
            i += 2
        else:
            inputs[key] = True
            i += 1

    # 从配置的 inputs 定义中填充默认值和 example
    for field_name, field_def in config.get("inputs", {}).items():
        if field_name not in inputs and "example" in field_def:
            val = field_def["example"]
            if field_def.get("type") == "object":
                try:
                    val = json.loads(val)
                except json.JSONDecodeError as e:
                    print(f"  ⚠️ 字段 {field_name} example 解析失败: {e}")
            inputs[field_name] = val

    print(f"🏭 Mify 造数工厂")
    print(f"📋 流程: {config['name']}")
    print(f"📦 输入: {json.dumps(inputs, ensure_ascii=False, indent=2)}")

    # 初始化
    mify = MifyClient(endpoint, token, user, sql_workflow_id,
                      http_workflow_id=http_workflow_id,
                      sql_token=sql_token)
    engine = FlowEngine(config, inputs, mify)

    # 获取 cookie（如果有 cookie_url 配置）
    cookie_url = config.get("config", {}).get("cookie_url")
    if cookie_url:
        print("\n📌 获取 Cookie...")
        engine.cookie = mify.get_cookie(cookie_url)
        if engine.cookie:
            print(f"  ✅ Cookie 获取成功 (长度: {len(engine.cookie)})")
        else:
            print(f"  ❌ Cookie 获取失败")
            return

    # 执行流程
    engine.run(save_state=args.save_state)


if __name__ == "__main__":
    main()
