#!/usr/bin/env python3
"""
扫描 configs/ 目录，自动生成 router.yaml 路由配置

用法：
    python3 gen-router.py

自动发现 configs/ 下所有 *-prpo.yaml 文件，生成路由映射到 router.yaml
"""
import yaml
from pathlib import Path

CONFIGS_DIR = Path(__file__).parent / "configs"
ROUTER_PATH = CONFIGS_DIR / "router.yaml"

# 扫描所有主版本 *-prpo.yaml，跳过历史版本文件（如 *-v2.yaml）
routes = {}
for f in sorted(CONFIGS_DIR.glob("*-prpo.yaml")):
    if "-v" in f.stem:
        continue
    # 文件名格式:
    #   znb-prpo.yaml      → orderType = ZNB
    #   zww-semi-prpo.yaml → orderType = ZWW_SEMI
    parts = f.stem.split("-")
    order_type = "_".join(parts[:-1]).upper()
    routes[order_type] = f"configs/{f.name}"
    print(f"  发现: {order_type} → {f.name}")

if not routes:
    print("❌ 未找到任何 *-prpo.yaml 配置文件")
    exit(1)

print(f"\n✅ 共发现 {len(routes)} 个订单类型: {', '.join(routes.keys())}")

# 读取公共配置（从任意一个子配置中取）
sample_config_path = CONFIGS_DIR / list(routes.values())[0].split("/")[1]
sample_config = yaml.safe_load(sample_config_path.read_text(encoding='utf-8'))
common_config = sample_config.get("config", {})
sample_inputs = sample_config.get("inputs", {})

# 生成 router.yaml
router = {
    "name": "SAP订单数据生成路由器",
    "description": f"自动发现 {len(routes)} 个订单类型: {', '.join(routes.keys())}",
    "inputs": {
        "orderType": {"label": "订单类型", "required": True, "example": list(routes.keys())[0]},
        **{k: v for k, v in sample_inputs.items() if k != "orderType"},
    },
    "config": common_config,
    "steps": [
        {
            "id": "get_cookie",
            "action": "http_call",
            "params": {
                "url": "{{config.cookie_url}}",
                "method": "GET",
            },
            "extract": {"cookie": "$.body.data.result.cookie"},
            "on_error": {"message": "cookie获取失败，请联系管理员"},
        },
        {
            "id": "route_order",
            "action": "route",
            "switch_on": "{{inputs.orderType}}",
            "routes": routes,
            "default_config": list(routes.values())[0],
            "goto_fail": "END_ROUTE_FAIL",
        },
    ],
    "terminals": {
        "SUCCESS": {"type": "success", "message": "路由执行完成"},
        "END_ROUTE_FAIL": {"type": "error", "message": "路由失败：不支持的订单类型 {{inputs.orderType}}"},
    },
}

ROUTER_PATH.write_text(yaml.dump(router, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding='utf-8')
print(f"\n✅ 已生成 {ROUTER_PATH}")
