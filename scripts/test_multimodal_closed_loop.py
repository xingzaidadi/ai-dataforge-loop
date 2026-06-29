#!/usr/bin/env python3
"""Smoke tests for the multimodal data-making closed loop.

The tests intentionally run in dry-run mode so they do not require SRM/SCM
network access, real cookies, database credentials, or Playwright browsers.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "DATAMAKE-SMOKE-TEST"
RUN_DIR = ROOT / "evidence" / "runs" / RUN_ID


def safe_print(value: str, *, stream=None) -> None:
    target = stream or sys.stdout
    try:
        print(value, file=target)
    except UnicodeEncodeError:
        encoding = getattr(target, "encoding", None) or "utf-8"
        safe_value = value.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe_value, file=target)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    safe_print(f"\n$ {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.stdout:
        safe_print(completed.stdout)
    if completed.stderr:
        safe_print(completed.stderr, stream=sys.stderr)
    if completed.returncode != 0:
        raise AssertionError(f"命令执行失败，退出码 {completed.returncode}: {' '.join(command)}")
    return completed


def load_json(path: Path) -> dict:
    if not path.exists():
        raise AssertionError(f"缺少输出文件: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def assert_file(path: Path) -> None:
    if not path.exists():
        raise AssertionError(f"缺少输出文件: {path}")
    if path.is_file() and path.stat().st_size == 0:
        raise AssertionError(f"输出文件为空: {path}")


def clean_run_dir() -> None:
    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)


def test_static_validation() -> None:
    run([sys.executable, "scripts/validate_skill.py"])


def test_closed_loop_dry_run() -> None:
    clean_run_dir()
    run([
        sys.executable,
        "tools/closed_loop_runner.py",
        "--dry-run",
        "--run-id",
        RUN_ID,
        "--text",
        "帮我造一条生态链 ZNB PRPO，造完做页面验收",
        "--config",
        "configs/znb-prpo.yaml",
        "--ui-config",
        "configs/ui-verify-prpo.yaml",
        "orderType=ZNB",
        "stockOrg=MI_IOT",
        "purchaseOrg=2120",
        "supplierCode=SUPPLIER_DEMO",
        'materials={"materialCode1":"MAT_DEMO"}',
        "projectCode=PROJECT_DEMO",
        "shipLocCode=LOC_DEMO",
    ])

    summary = load_json(RUN_DIR / "summary.json")
    intent = load_json(RUN_DIR / "intent.json")
    datamake = load_json(RUN_DIR / "datamake-result.json")
    ui_verify = load_json(RUN_DIR / "ui-verify-result.json")

    if summary.get("status") != "SUCCESS":
        raise AssertionError(f"summary.status 应为 SUCCESS，实际为 {summary.get('status')}")
    if intent.get("data", {}).get("intent", {}).get("orderType") != "ZNB":
        raise AssertionError("意图识别未提取到 orderType=ZNB")
    if datamake.get("status") != "SKIPPED":
        raise AssertionError("dry-run 下造数步骤应为 SKIPPED")
    if ui_verify.get("status") != "SKIPPED":
        raise AssertionError("dry-run 下 UI 验收应为 SKIPPED")
    if not summary.get("report"):
        raise AssertionError("summary.json 缺少本次报告链接 report")
    if not summary.get("reportIndex"):
        raise AssertionError("summary.json 缺少报告索引链接 reportIndex")

    for file_name in [
        "intent.json",
        "params.json",
        "datamake-result.json",
        "ui-verify-result.json",
        "evidence-pack.json",
        "summary.json",
        "report.html",
    ]:
        assert_file(RUN_DIR / file_name)

    report_html = (RUN_DIR / "report.html").read_text(encoding="utf-8")
    required_report_sections = [
        "执行结论",
        "本次造出的数据",
        "页面验收结果",
        "造数前数据清洗",
        "PR 号",
        "PO 号",
        "ERP 单号",
        "失败诊断建议",
        "页面截图证据",
        "metric-card",
        "conclusion-title",
    ]
    for section in required_report_sections:
        if section not in report_html:
            raise AssertionError(f"可视化报告缺少关键内容: {section}")

    index_path = ROOT / "evidence" / "index.html"
    assert_file(index_path)
    index_html = index_path.read_text(encoding="utf-8")
    if RUN_ID not in index_html:
        raise AssertionError("报告索引页未包含本次 run_id")
    if "runs/DATAMAKE-SMOKE-TEST/report.html" not in index_html:
        raise AssertionError("报告索引页未包含本次报告链接")


def test_screenshot_json_adapter() -> None:
    run_id = "DATAMAKE-SCREENSHOT-TEST"
    run_dir = ROOT / "evidence" / "runs" / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    sample_path = ROOT / "evidence" / "screenshot-input.json"
    sample_path.write_text(
        json.dumps(
            {
                "taskType": "intent_extract",
                "sceneType": "ZNB",
                "stockOrgCN": "iot",
                "supplierCode": "SUPPLIER_DEMO",
                "materials": [
                    {"materialCode": "MAT_DEMO_A", "quantity": "2"},
                    {"materialCode": "MAT_DEMO_B", "quantity": "3"},
                ],
                "projectCode": "PROJECT_DEMO",
                "shipLocCode": "LOC_DEMO",
                "nextAction": "RUN_DATAMAKE",
                "confidence": 0.92,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run([
        sys.executable,
        "tools/closed_loop_runner.py",
        "--dry-run",
        "--run-id",
        run_id,
        "--text",
        "??????? SCM ??????????",
        "--config",
        "configs/znb-prpo.yaml",
        "--ui-config",
        "configs/ui-verify-prpo.yaml",
        "--screenshot-json",
        str(sample_path),
    ])

    params = load_json(run_dir / "params.json").get("params", {})
    screenshot_result = load_json(run_dir / "screenshot-params-result.json")
    if params.get("stockOrg") != "MI_IOT":
        raise AssertionError("???????? stockOrg=MI_IOT")
    if params.get("purchaseOrg") != "2120":
        raise AssertionError("???????? purchaseOrg=2120")
    if params.get("materials", {}).get("materialCode1") != "MAT_DEMO_A":
        raise AssertionError("???????? materialCode1=MAT_DEMO_A")
    if params.get("materials", {}).get("materialCode2") != "MAT_DEMO_B":
        raise AssertionError("???????? materialCode2=MAT_DEMO_B")
    if screenshot_result.get("data", {}).get("nextAction") != "RUN_DATAMAKE":
        raise AssertionError("???? nextAction ??? RUN_DATAMAKE")
    report_html = (run_dir / "report.html").read_text(encoding="utf-8")
    for keyword in ["screenshot_params_adapter", "MAT_DEMO_A", "RUN_DATAMAKE"]:
        if keyword not in report_html:
            raise AssertionError(f"????????????: {keyword}")


def test_failure_diagnosis_rule() -> None:
    if not RUN_DIR.exists():
        raise AssertionError("请先执行 dry-run 闭环测试")
    failed_shot = RUN_DIR / "screenshots" / "failed-99.png"
    failed_shot.parent.mkdir(parents=True, exist_ok=True)
    failed_shot.write_bytes(b"fake-png-for-smoke-test")
    (RUN_DIR / "ui-verify-result.json").write_text(
        json.dumps(
            {
                "name": "ui_verify",
                "status": "FAILED",
                "detail": "UI 验收失败: Timeout waiting for selector",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run([sys.executable, "tools/failure_diagnose.py", "--run-dir", str(RUN_DIR)])
    diagnosis = load_json(RUN_DIR / "diagnosis.json")
    suggestions = diagnosis.get("data", {}).get("suggestions", [])
    if not suggestions:
        raise AssertionError("失败诊断未生成 suggestions")
    if not any("超时" in item.get("category", "") or "Timeout" in item.get("evidence", "") for item in suggestions):
        raise AssertionError("失败诊断未命中 Timeout 规则")


def main() -> int:
    tests = [
        test_static_validation,
        test_closed_loop_dry_run,
        test_screenshot_json_adapter,
        test_failure_diagnosis_rule,
    ]
    for test in tests:
        safe_print(f"\n=== {test.__name__} ===")
        test()
    safe_print("\n[OK] 多模态闭环冒烟测试通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
