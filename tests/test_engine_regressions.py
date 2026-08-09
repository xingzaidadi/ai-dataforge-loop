#!/usr/bin/env python3
"""引擎核心行为回归测试（保护本轮 A 组修复不被误改回去）。

覆盖两个最易回归的引擎缺陷：
  ① http_call 的 goto 必须被尊重（历史缺陷：_do_http_call 无条件 return None，
     导致 goto 被静默丢弃、引擎退化为顺序执行）。
  ② 空值归一判定：None / '' / 'None' / 'null' 互认为空，非空值才按字面量比对
     （== null、!= '' 等条件在真实数据里高频出现）。

运行：python tests/test_engine_regressions.py
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


class _FakeMify:
    """最小 mify 桩：不触网，返回固定 200 空响应，记录被调 URL。"""

    def __init__(self):
        self.calls = []

    def http_call(self, url, method, body, cookie, headers):
        self.calls.append(url)
        return {"status_code": 200, "body": {"code": "0", "data": {}}}


def _engine(inputs=None):
    """构造仅用于单步求值的引擎实例。"""
    return FlowEngine(config={"steps": [], "terminals": {}}, inputs=inputs or {}, mify=_FakeMify())


# ═══════════════════════════════════════════════
#  ① http_call 尊重 goto
# ═══════════════════════════════════════════════

def test_http_call_returns_goto():
    """声明了 goto 的 http_call 必须返回该 goto（而非静默 None）。"""
    eng = _engine()
    step = {
        "id": "close_history_po",
        "action": "http_call",
        "params": {"url": "http://x/isc/srm-tools/po/close", "method": "GET"},
        "goto": "reopen_history_po",
    }
    assert eng._do_http_call(step) == "reopen_history_po"


def test_http_call_no_goto_returns_none():
    """未声明 goto 时返回 None，保持顺序执行不变（不回归成乱跳）。"""
    eng = _engine()
    step = {
        "id": "get_po_info",
        "action": "http_call",
        "params": {"url": "http://x/isc/sourcing-data/newGetByOptions", "method": "POST"},
    }
    assert eng._do_http_call(step) is None


def test_http_call_now_ts_refreshed():
    """每次 http_call 都应刷新 now_ts（供 po/close|open 的 cache-buster key）。"""
    eng = _engine()
    step = {"id": "s", "action": "http_call", "params": {"url": "http://x/y", "method": "GET"}}
    eng._do_http_call(step)
    assert eng.context.get("now_ts", "").isdigit()


def test_http_call_goto_end_to_end_no_fallthrough():
    """端到端复现文章场景：machine_fee 分支的 http_call 带 goto:SUCCESS 应干净收尾，
    绝不能"串味"顺序落到下一条（非 machine_fee 的诊断修复）分支。

    这是对长文/QA "早期 http_call 吞 goto、后在引擎层修正" 说法的真实回归证明：
    若 goto 再次被静默丢弃，force_new_price 会 fall-through 执行 wrong_branch，
    fake.calls 里就会出现 wrong_branch 的 URL、断言失败。
    """
    fake = _FakeMify()
    config = {
        "steps": [
            {
                "id": "force_new_price",  # machine_fee 分支：推价成功后直接收尾
                "action": "http_call",
                "params": {"url": "http://x/force_new_price", "method": "POST"},
                "goto": "SUCCESS",
            },
            {
                "id": "wrong_branch",  # 非 machine_fee 分支：绝不该被执行到
                "action": "http_call",
                "params": {"url": "http://x/wrong_branch", "method": "POST"},
            },
        ],
        "terminals": {"SUCCESS": {"type": "success", "message": "价格治理完成"}},
    }
    eng = FlowEngine(config=config, inputs={}, mify=fake)
    eng.run()
    assert "http://x/force_new_price" in fake.calls
    assert not any("wrong_branch" in u for u in fake.calls), (
        f"http_call 的 goto 被吞了，串味执行了 wrong_branch：{fake.calls}"
    )


# ═══════════════════════════════════════════════
#  ② 空值归一判定（== / !=）
# ═══════════════════════════════════════════════

def test_none_equals_empty_string():
    """缺失变量(None) == '' 应为真（历史上二者被判不等，导致分支漂移）。"""
    eng = _engine({})  # erp_no 缺失 → None
    assert eng._eval_condition_expr("{{inputs.erp_no}} == ''") is True


def test_literal_none_equals_empty():
    """DB/接口回吐字面量 'None' 或 'null' 也应视作空。"""
    eng = _engine({"erp_no": "None"})
    assert eng._eval_condition_expr("{{inputs.erp_no}} == ''") is True
    eng2 = _engine({"erp_no": "null"})
    assert eng2._eval_condition_expr("{{inputs.erp_no}} == null") is True


def test_nonempty_not_equal_empty():
    """真实 ERP 号非空 → != '' 为真（check_erp 判定「已回填」的核心）。"""
    eng = _engine({"erp_no": "4500236548"})
    assert eng._eval_condition_expr("{{inputs.erp_no}} != ''") is True
    assert eng._eval_condition_expr("{{inputs.erp_no}} == ''") is False


def test_nonempty_literal_equality_preserved():
    """两个非空值仍按字面量严格比对，不被归一逻辑吞掉。"""
    eng = _engine({"a": "ZNB"})
    assert eng._eval_condition_expr("{{inputs.a}} == 'ZNB'") is True
    assert eng._eval_condition_expr("{{inputs.a}} == 'ZWW'") is False


if __name__ == "__main__":
    test_http_call_returns_goto()
    test_http_call_no_goto_returns_none()
    test_http_call_now_ts_refreshed()
    test_http_call_goto_end_to_end_no_fallthrough()
    test_none_equals_empty_string()
    test_literal_none_equals_empty()
    test_nonempty_not_equal_empty()
    test_nonempty_literal_equality_preserved()
    print("✅ tests/test_engine_regressions.py 全部通过")
