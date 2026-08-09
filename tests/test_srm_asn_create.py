#!/usr/bin/env python3
"""ASN 承接分支解析单元测试。

运行：python tests/test_srm_asn_create.py
（无 pytest 依赖，纯 assert，便于在无框架环境下自检）
"""

import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

import tempfile  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from srm_asn_create import resolve_category, resolve_scene, run_srm_asn_create  # noqa: E402


def test_resolve_category():
    # 三大供应商编码
    assert resolve_category("100171", "ZNB", None, None) == "GAOTONG"
    assert resolve_category("126929", "ZNB", None, None) == "TI"
    assert resolve_category("100227", "ZNB", None, None) == "MTK"
    # int 形式的供应商编码（parse_kv_pairs 会 json.loads 成 int）
    assert resolve_category(100171, "ZNB", None, None) == "GAOTONG"
    # 大货：非三大 + 拉料指令
    assert resolve_category("999999", "ZWW", "2509220000000001", "X") == "CIN"
    # 成品：ZWW/ZPJ/ZDB + 料号 s/f 开头
    assert resolve_category("999999", "ZWW", None, "S123") == "CHENGPIN"
    assert resolve_category("999999", "ZPJ", None, "f999") == "CHENGPIN"
    # 寄存
    assert resolve_category("999999", "ZJC", None, None) == "JC"
    # 独立需求兜底
    assert resolve_category("999999", "ZNB", None, None) == "PO"


def test_resolve_scene():
    # 高通单行
    s = resolve_scene("GAOTONG", 1)
    # 行序严格升序：1行=369、2行=339、3行=370（对照 _SCENE_MAP 与机器人 YAML 场景名）
    assert s["taskType"] == "GAOTONG_1" and s["sceneId"] == 369 and s["resolved"]
    # 大货单行
    s = resolve_scene("CIN", 1)
    assert s["taskType"] == "CIN_1" and s["sceneId"] == 378 and s["resolved"]
    # 行数封顶：三大最多 3 行（3行=370，锁死行序防回归）
    s = resolve_scene("GAOTONG", 9)
    assert s["taskType"] == "GAOTONG_3" and s["sceneId"] == 370
    # 成品最多 2 行
    s = resolve_scene("CHENGPIN", 3)
    assert s["taskType"] == "CHENGPIN_2"
    # 未预置类别：不谎报，标 resolved=False
    s = resolve_scene("UNKNOWN", 1)
    assert s["resolved"] is False and s["sceneId"] == ""


def test_unresolved_scene_blocks():
    """未命中场景（resolved=False、空 sceneId）时，run_srm_asn_create 必须阻断，
    返回 BLOCKED，绝不带空 sceneId 进入真实执行。"""
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        # 显式传入未预置类别，触发 resolve_scene 未命中
        result = run_srm_asn_create(
            config="configs/srm-asn-create.yaml",
            params={"poNo": "PO-TEST-001", "asnCategory": "UNKNOWN_CAT", "lineCount": 1},
            run_dir=run_dir,
            dry_run=True,
        )
    assert result.status == "BLOCKED", f"期望 BLOCKED，实际 {result.status}"
    assert result.data.get("resolved") is False
    assert "场景未接入" in result.detail
    # 不应生成任何真实执行的 command
    assert "command" not in result.data


if __name__ == "__main__":
    test_resolve_category()
    test_resolve_scene()
    test_unresolved_scene_blocks()
    print("✅ tests/test_srm_asn_create.py 全部通过")
