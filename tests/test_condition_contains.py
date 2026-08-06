#!/usr/bin/env python3
"""条件表达式 contains 运算符 + 寻源分支路由 单元测试。

验证两个引擎修复：
  ① _eval_condition_expr 支持 "contains" 子串判断
  ② check_price_type 分支：priceType 含 machine_fee → then；否则 → else

运行：python tests/test_condition_contains.py
（无 pytest 依赖，纯 assert）
"""

import sys
from pathlib import Path

# Windows 控制台默认 GBK，引擎 print 含 emoji 会抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.flow import FlowEngine  # noqa: E402


def _engine(inputs):
    """构造仅用于条件求值的引擎实例（mify=None，不触网）。"""
    return FlowEngine(config={"steps": [], "terminals": {}}, inputs=inputs, mify=None)


def test_contains_true():
    eng = _engine({"priceType": "mav_fee,machine_fee,odm_owned_fee"})
    assert eng._eval_condition_expr("{{inputs.priceType}} contains 'machine_fee'") is True


def test_contains_false():
    eng = _engine({"priceType": "mav_fee,odm_owned_fee"})
    assert eng._eval_condition_expr("{{inputs.priceType}} contains 'machine_fee'") is False


def test_contains_none_left():
    eng = _engine({})  # priceType 缺失 → resolve_ref 返回 None
    assert eng._eval_condition_expr("{{inputs.priceType}} contains 'machine_fee'") is False


def test_contains_dynamic_right():
    # 右值也是引用时应解析后再比对
    eng = _engine({"priceType": "a,b,machine_fee", "needle": "machine_fee"})
    assert eng._eval_condition_expr("{{inputs.priceType}} contains {{inputs.needle}}") is True


def test_branch_routing_machine_fee():
    """check_price_type 命中 machine_fee → 走 then=create_machine_fee。"""
    eng = _engine({"priceType": "machine_fee"})
    step = {
        "id": "check_price_type",
        "action": "condition",
        "if": "{{inputs.priceType}} contains 'machine_fee'",
        "then": "create_machine_fee",
        "else": "check_asl",
    }
    assert eng._do_condition(step) == "create_machine_fee"


def test_branch_routing_non_machine_fee():
    """priceType 不含 machine_fee → 走 else=check_asl。"""
    eng = _engine({"priceType": "mav_fee,odm_owned_fee"})
    step = {
        "id": "check_price_type",
        "action": "condition",
        "if": "{{inputs.priceType}} contains 'machine_fee'",
        "then": "create_machine_fee",
        "else": "check_asl",
    }
    assert eng._do_condition(step) == "check_asl"


if __name__ == "__main__":
    test_contains_true()
    test_contains_false()
    test_contains_none_left()
    test_contains_dynamic_right()
    test_branch_routing_machine_fee()
    test_branch_routing_non_machine_fee()
    print("✅ tests/test_condition_contains.py 全部通过")
