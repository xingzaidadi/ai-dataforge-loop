#!/usr/bin/env python3
"""Build a visual HTML report for multimodal data-making evidence."""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from common import StepResult, read_json, write_json


def _safe_json(run_dir: Path, file_name: str) -> dict[str, Any]:
    path = run_dir / file_name
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _status_class(status: str) -> str:
    normalized = (status or "UNKNOWN").upper()
    if normalized in {"SUCCESS", "PASS"}:
        return "success"
    if normalized in {"FAILED", "FAIL"}:
        return "failed"
    if normalized in {"PARTIAL", "RECOVERED"}:
        return "warning"
    if normalized == "SKIPPED":
        return "skipped"
    return "unknown"


def _badge(status: str) -> str:
    status = status or "UNKNOWN"
    return f"<span class='badge {_status_class(status)}'>{_escape(status)}</span>"


def _card(label: str, value: Any, status: str = "") -> str:
    klass = _status_class(status) if status else "neutral"
    return f"""
    <div class="metric-card {klass}">
      <div class="metric-label">{_escape(label)}</div>
      <div class="metric-value">{_escape(value)}</div>
    </div>
    """


def _table(rows: list[tuple[str, Any]]) -> str:
    body = "\n".join(
        f"<tr><th>{_escape(key)}</th><td>{_escape(value)}</td></tr>"
        for key, value in rows
        if value not in (None, "", [], {})
    )
    return f"<table class='kv-table'>{body or '<tr><td>暂无数据</td></tr>'}</table>"


def _params_table(params: dict[str, Any]) -> str:
    rows = []
    for key, value in params.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        rows.append((key, value))
    return _table(rows)


def _business_value(data: dict[str, Any], key: str) -> Any:
    return data.get(key) or "待生成" if key in {"prNo", "poNo", "erpNo"} else data.get(key, "")


def _business_data_table(business_data: dict[str, Any]) -> str:
    materials = business_data.get("materials", "")
    if isinstance(materials, (dict, list)):
        materials = json.dumps(materials, ensure_ascii=False)
    return _table([
        ("PR 号", _business_value(business_data, "prNo")),
        ("PO 号", _business_value(business_data, "poNo")),
        ("ERP 单号", _business_value(business_data, "erpNo")),
        ("订单类型", business_data.get("orderType", "")),
        ("库存组织", business_data.get("stockOrg", "")),
        ("采购组织", business_data.get("purchaseOrg", "")),
        ("供应商", business_data.get("supplierCode", "")),
        ("物料", materials),
        ("项目号", business_data.get("projectCode", "")),
        ("发货地点", business_data.get("shipLocCode", "")),
    ])


def _conclusion_panel(overall_status: str, datamake: dict[str, Any], ui_verify: dict[str, Any], business_data: dict[str, Any]) -> str:
    datamake_status = datamake.get("status", "UNKNOWN")
    ui_status = ui_verify.get("status", "UNKNOWN")
    if overall_status == "SUCCESS":
        conclusion = "造数链路执行成功，本次数据可进入后续测试。"
    elif overall_status == "PARTIAL":
        conclusion = "造数主流程已执行，但页面验收或后续检查未完全通过，需按诊断建议确认后使用。"
    elif overall_status == "FAILED":
        conclusion = "造数失败，本次未产出可用测试数据。"
    else:
        conclusion = "当前状态待确认，请查看造数结果和验收结果。"
    key_numbers = [
        ("PR", business_data.get("prNo", "待生成")),
        ("PO", business_data.get("poNo", "待生成")),
        ("ERP", business_data.get("erpNo", "待生成")),
    ]
    pills = "".join(f"<span class='data-pill'><b>{_escape(label)}</b>{_escape(value)}</span>" for label, value in key_numbers)
    return f"""
    <div class="conclusion {_status_class(overall_status)}">
      <div>
        <div class="conclusion-title">{_escape(conclusion)}</div>
        <div class="conclusion-sub">造数：{_badge(datamake_status)} 页面验收：{_badge(ui_status)}</div>
      </div>
      <div class="data-pills">{pills}</div>
    </div>
    """


def _clean_result_panel(pre_clean: dict[str, Any]) -> str:
    if not pre_clean:
        return (
            "<div class='empty'>本次未启用前置清洗。启用后这里会展示 ASL、费用 PN、费用项、定价单的"
            "检查结果、修复动作和最终状态。</div>"
        )
    data = pre_clean.get("data", {}) or {}
    parsed = data.get("parsed", {}) or {}
    extracted = parsed.get("steps_extracted", {}) or {}
    rows = [
        ("清洗状态", pre_clean.get("status", "UNKNOWN")),
        ("清洗说明", pre_clean.get("detail", "")),
        ("断言结果", data.get("assert_detail", "")),
        ("返回码", data.get("returncode", "")),
        ("提取变量数", len(extracted) if extracted else ""),
    ]
    command = data.get("command")
    if command:
        rows.append(("执行命令", " ".join(command)))
    if data.get("errors"):
        rows.append(("输入校验错误", "; ".join(data.get("errors", []))))
    return _table(rows)


def _stage(name: str, status: str, detail: str, extra: str = "") -> str:
    return f"""
    <div class="stage {_status_class(status)}">
      <div class="stage-dot"></div>
      <div class="stage-main">
        <div class="stage-title">{_escape(name)} {_badge(status)}</div>
        <div class="stage-detail">{_escape(detail)}</div>
        {extra}
      </div>
    </div>
    """


def _ui_steps(ui_verify: dict[str, Any]) -> str:
    steps = ui_verify.get("data", {}).get("steps", [])
    if not steps:
        config = ui_verify.get("data", {}).get("config", {})
        return _table([
            ("验收模式", ui_verify.get("status", "UNKNOWN")),
            ("说明", ui_verify.get("detail", "")),
            ("页面入口", config.get("base_url", "")),
            ("验收路径", config.get("url", "")),
        ])

    rows = []
    for step in steps:
        screenshot = step.get("screenshot", "")
        shot_name = Path(screenshot).name if screenshot else ""
        rows.append(
            "<tr>"
            f"<td>{_escape(step.get('index'))}</td>"
            f"<td>{_escape(step.get('desc'))}</td>"
            f"<td>{_badge(step.get('status', 'UNKNOWN'))}</td>"
            f"<td>{_escape(step.get('error', ''))}</td>"
            f"<td>{_escape(shot_name)}</td>"
            "</tr>"
        )
    return (
        "<table class='data-table'><thead><tr>"
        "<th>#</th><th>步骤</th><th>状态</th><th>错误</th><th>截图</th>"
        "</tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table>"
    )


def _diagnosis_panel(diagnosis: dict[str, Any]) -> str:
    suggestions = diagnosis.get("data", {}).get("suggestions", [])
    if not suggestions:
        return "<div class='empty'>本次未触发失败诊断。</div>"
    items = []
    for suggestion in suggestions:
        items.append(
            "<li>"
            f"<strong>{_escape(suggestion.get('category', '诊断建议'))}</strong>"
            f"<p>证据：{_escape(suggestion.get('evidence', ''))}</p>"
            f"<p>建议：{_escape(suggestion.get('action', ''))}</p>"
            "</li>"
        )
    return "<ol class='diagnosis-list'>" + "\n".join(items) + "</ol>"


def _screenshots_panel(run_dir: Path) -> str:
    screenshots = sorted((run_dir / "screenshots").glob("*.png"))
    if not screenshots:
        dry_run_note = run_dir / "screenshots" / "ui-verify-dry-run.txt"
        if dry_run_note.exists():
            return "<div class='empty'>dry-run 模式未启动浏览器；真实执行后这里会展示页面截图。</div>"
        return "<div class='empty'>暂无截图。</div>"
    figures = []
    for path in screenshots:
        figures.append(
            "<figure>"
            f"<img src='screenshots/{_escape(path.name)}' alt='{_escape(path.name)}' />"
            f"<figcaption>{_escape(path.name)}</figcaption>"
            "</figure>"
        )
    return "<div class='screenshot-grid'>" + "\n".join(figures) + "</div>"


def _raw_links(run_dir: Path) -> str:
    files = [
        "intent.json",
        "params.json",
        "datamake-result.json",
        "ui-verify-result.json",
        "diagnosis.json",
        "summary.json",
    ]
    links = []
    for file_name in files:
        if (run_dir / file_name).exists():
            links.append(f"<a href='{_escape(file_name)}'>{_escape(file_name)}</a>")
    return "<div class='raw-links'>" + "\n".join(links) + "</div>"


def _run_sort_key(path: Path) -> float:
    summary_path = path / "summary.json"
    report_path = path / "report.html"
    target = summary_path if summary_path.exists() else report_path
    if target.exists():
        return target.stat().st_mtime
    return path.stat().st_mtime


def build_report_index(evidence_root: Path, limit: int = 50) -> Path:
    runs = []
    if evidence_root.exists():
        run_dirs = [path for path in evidence_root.iterdir() if path.is_dir()]
        for run_dir in sorted(run_dirs, key=_run_sort_key, reverse=True)[:limit]:
            report_path = run_dir / "report.html"
            summary = _safe_json(run_dir, "summary.json")
            datamake = _safe_json(run_dir, "datamake-result.json")
            business_data = (datamake.get("data", {}) or {}).get("businessData", {}) or {}
            if not report_path.exists():
                continue
            runs.append({
                "runId": summary.get("runId") or run_dir.name,
                "status": summary.get("status", "UNKNOWN"),
                "config": summary.get("config", ""),
                "prNo": business_data.get("prNo", "待生成"),
                "poNo": business_data.get("poNo", "待生成"),
                "erpNo": business_data.get("erpNo", "待生成"),
                "report": f"runs/{run_dir.name}/report.html",
                "mtime": datetime.fromtimestamp(report_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })

    rows = []
    for item in runs:
        rows.append(
            "<tr>"
            f"<td><a href='{_escape(item['report'])}'>{_escape(item['runId'])}</a></td>"
            f"<td>{_badge(item['status'])}</td>"
            f"<td>{_escape(item['prNo'])}</td>"
            f"<td>{_escape(item['poNo'])}</td>"
            f"<td>{_escape(item['erpNo'])}</td>"
            f"<td>{_escape(item['config'])}</td>"
            f"<td>{_escape(item['mtime'])}</td>"
            "</tr>"
        )
    index_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>AI 数据智造报告索引</title>
  <style>
    body {{ margin: 0; background: #f5f7fb; color: #172033; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; }}
    header {{ padding: 30px 40px; color: white; background: linear-gradient(135deg, #172033 0%, #1e3a8a 54%, #2563eb 100%); }}
    h1 {{ margin: 0 0 8px; }}
    main {{ padding: 28px 40px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 14px; overflow: hidden; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06); }}
    th, td {{ padding: 12px 14px; border-bottom: 1px solid #e6eaf2; text-align: left; }}
    th {{ background: #f8fafc; color: #475569; }}
    a {{ color: #1d4ed8; text-decoration: none; font-weight: 700; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; color: white; font-size: 12px; }}
    .badge.success {{ background: #16a34a; }}
    .badge.failed {{ background: #dc2626; }}
    .badge.warning {{ background: #f59e0b; }}
    .badge.skipped {{ background: #64748b; }}
    .badge.unknown {{ background: #2563eb; }}
    .empty {{ padding: 18px; background: white; border-radius: 12px; color: #667085; }}
  </style>
</head>
<body>
  <header>
    <h1>AI 数据智造报告索引</h1>
    <div>每次执行生成一份独立报告，这里展示最近 {limit} 次。</div>
  </header>
  <main>
    {"<table><thead><tr><th>运行编号</th><th>状态</th><th>PR</th><th>PO</th><th>ERP</th><th>配置</th><th>生成时间</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>" if rows else "<div class='empty'>暂无报告。</div>"}
  </main>
</body>
</html>
"""
    index_path = evidence_root.parent / "index.html"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(index_html, encoding="utf-8")
    return index_path


def build_evidence_pack(run_dir: Path, title: str = "AI 数据智造多模态闭环报告") -> StepResult:
    summary = _safe_json(run_dir, "summary.json")
    intent_doc = _safe_json(run_dir, "intent.json")
    params_doc = _safe_json(run_dir, "params.json")
    pre_clean = _safe_json(run_dir, "srm-price-clean-result.json") or (summary.get("preClean") or {})
    datamake = _safe_json(run_dir, "datamake-result.json")
    ui_verify = _safe_json(run_dir, "ui-verify-result.json")
    diagnosis = _safe_json(run_dir, "diagnosis.json")

    run_id = summary.get("runId") or run_dir.name
    overall_status = summary.get("status", "UNKNOWN")
    intent_data = intent_doc.get("data", {})
    intent = intent_data.get("intent", {})
    missing_fields = intent_data.get("missingFields", [])
    params = params_doc.get("params", {})
    datamake_data = datamake.get("data", {})
    business_data = datamake_data.get("businessData") or {}
    if params:
        business_data = {**params, **business_data}
    command = datamake_data.get("command", [])
    screenshots = sorted((run_dir / "screenshots").glob("*.png"))

    stage_html = "\n".join([
        _stage(
            "多模态意图识别",
            intent_doc.get("status", "UNKNOWN"),
            intent_doc.get("detail", ""),
            _table([
                ("输入类型", intent.get("sourceType", "")),
                ("订单类型", intent.get("orderType", "")),
                ("采购组织", intent.get("purchaseOrgCN", "")),
                ("库存组织", intent.get("stockOrg", "")),
                ("缺失字段", ", ".join(missing_fields)),
            ]),
        ),
        _stage(
            "参数收口与执行确认",
            "SUCCESS" if params else "PARTIAL",
            "已形成最终执行参数" if params else "暂无最终参数",
            _params_table(params),
        ),
        _stage(
            "PRPO 造数执行",
            datamake.get("status", "UNKNOWN"),
            datamake.get("detail", ""),
            _table([
                ("流程配置", params_doc.get("config", "")),
                ("执行命令", " ".join(command) if command else ""),
                ("返回码", datamake_data.get("returncode", "")),
            ]),
        ),
        _stage(
            "SCM/SRM 页面验收",
            ui_verify.get("status", "UNKNOWN"),
            ui_verify.get("detail", ""),
            _ui_steps(ui_verify),
        ),
    ])

    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{_escape(title)}</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #172033;
      --muted: #667085;
      --line: #e6eaf2;
      --success: #16a34a;
      --failed: #dc2626;
      --warning: #f59e0b;
      --skipped: #64748b;
      --primary: #2563eb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    }}
    .hero {{
      padding: 36px 44px;
      background: linear-gradient(135deg, #172033 0%, #1e3a8a 54%, #2563eb 100%);
      color: white;
    }}
    .hero h1 {{ margin: 0 0 10px; font-size: 30px; }}
    .hero p {{ margin: 0; color: #dbeafe; }}
    .container {{ padding: 28px 44px 44px; }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .metric-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-left: 5px solid var(--primary);
      border-radius: 14px;
      padding: 16px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
    }}
    .metric-card.success {{ border-left-color: var(--success); }}
    .metric-card.failed {{ border-left-color: var(--failed); }}
    .metric-card.warning {{ border-left-color: var(--warning); }}
    .metric-card.skipped {{ border-left-color: var(--skipped); }}
    .metric-label {{ color: var(--muted); font-size: 13px; }}
    .metric-value {{ margin-top: 8px; font-size: 22px; font-weight: 750; word-break: break-all; }}
    .conclusion {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: center;
      padding: 20px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: #f8fafc;
    }}
    .conclusion.success {{ background: #f0fdf4; border-color: #bbf7d0; }}
    .conclusion.failed {{ background: #fef2f2; border-color: #fecaca; }}
    .conclusion.warning {{ background: #fffbeb; border-color: #fde68a; }}
    .conclusion-title {{ font-size: 20px; font-weight: 800; }}
    .conclusion-sub {{ margin-top: 10px; color: var(--muted); }}
    .data-pills {{ display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }}
    .data-pill {{
      min-width: 120px;
      padding: 10px 12px;
      border-radius: 12px;
      background: white;
      border: 1px solid var(--line);
      box-shadow: 0 4px 14px rgba(15, 23, 42, 0.05);
    }}
    .data-pill b {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 4px; }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 22px;
      margin: 18px 0;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
    }}
    h2 {{ margin: 0 0 16px; font-size: 20px; }}
    .stage {{
      display: grid;
      grid-template-columns: 18px 1fr;
      gap: 14px;
      padding: 16px 0;
      border-bottom: 1px solid var(--line);
    }}
    .stage:last-child {{ border-bottom: 0; }}
    .stage-dot {{
      width: 14px;
      height: 14px;
      border-radius: 50%;
      margin-top: 5px;
      background: var(--primary);
    }}
    .stage.success .stage-dot {{ background: var(--success); }}
    .stage.failed .stage-dot {{ background: var(--failed); }}
    .stage.warning .stage-dot {{ background: var(--warning); }}
    .stage.skipped .stage-dot {{ background: var(--skipped); }}
    .stage-title {{ font-weight: 750; font-size: 16px; }}
    .stage-detail {{ margin: 8px 0 12px; color: var(--muted); }}
    .badge {{
      display: inline-block;
      margin-left: 8px;
      padding: 2px 8px;
      border-radius: 999px;
      color: white;
      font-size: 12px;
      vertical-align: middle;
    }}
    .badge.success {{ background: var(--success); }}
    .badge.failed {{ background: var(--failed); }}
    .badge.warning {{ background: var(--warning); }}
    .badge.skipped {{ background: var(--skipped); }}
    .badge.unknown {{ background: var(--primary); }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ width: 180px; color: var(--muted); font-weight: 650; }}
    .data-table th {{ width: auto; background: #f8fafc; color: #334155; }}
    .diagnosis-list {{ margin: 0; padding-left: 22px; }}
    .diagnosis-list li {{ margin: 12px 0; }}
    .diagnosis-list p {{ margin: 6px 0; color: var(--muted); }}
    .screenshot-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    figure {{ margin: 0; }}
    img {{ width: 100%; border: 1px solid var(--line); border-radius: 12px; background: #fff; }}
    figcaption {{ margin-top: 8px; color: var(--muted); font-size: 13px; }}
    .empty {{ color: var(--muted); padding: 12px; background: #f8fafc; border-radius: 10px; }}
    .raw-links a {{
      display: inline-block;
      margin: 6px 8px 0 0;
      padding: 8px 10px;
      border-radius: 8px;
      background: #eff6ff;
      color: #1d4ed8;
      text-decoration: none;
      font-size: 13px;
    }}
    @media (max-width: 980px) {{
      .metric-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .screenshot-grid {{ grid-template-columns: 1fr; }}
      .conclusion {{ display: block; }}
      .data-pills {{ justify-content: flex-start; margin-top: 16px; }}
      .container {{ padding: 20px; }}
      .hero {{ padding: 28px 20px; }}
    }}
  </style>
</head>
<body>
  <div class="hero">
    <h1>{_escape(title)}</h1>
    <p>从多模态输入识别、参数收口、PRPO 造数到页面验收与失败诊断的完整执行报告</p>
  </div>
  <main class="container">
    <div class="metric-grid">
      {_card("执行结果", overall_status, overall_status)}
      {_card("PR 号", business_data.get("prNo", "待生成"))}
      {_card("PO 号", business_data.get("poNo", "待生成"))}
      {_card("ERP 单号", business_data.get("erpNo", "待生成"))}
    </div>

    <section>
      <h2>一、执行结论</h2>
      {_conclusion_panel(overall_status, datamake, ui_verify, business_data)}
    </section>

    <section>
      <h2>二、本次造出的数据</h2>
      {_business_data_table(business_data)}
    </section>

    <section>
      <h2>三、页面验收结果</h2>
      {_table([
          ("验收系统", "SCM/SRM（按 ui-verify 配置）"),
          ("验收状态", ui_verify.get("status", "UNKNOWN")),
          ("验收说明", ui_verify.get("detail", "")),
          ("截图数量", len(screenshots)),
      ])}
      {_ui_steps(ui_verify)}
    </section>

    <section>
      <h2>四、造数前数据清洗</h2>
      {_clean_result_panel(pre_clean)}
    </section>

    <section>
      <h2>五、多模态输入识别</h2>
      {_table([
          ("报告生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
          ("运行目录", run_dir),
          ("造数配置", summary.get("config", "")),
          ("输入类型", intent.get("sourceType", "")),
          ("识别订单类型", intent.get("orderType", "")),
          ("识别采购组织", intent.get("purchaseOrgCN", "")),
          ("缺失字段", ", ".join(missing_fields)),
      ])}
    </section>

    <section>
      <h2>六、PRPO 造数过程</h2>
      {stage_html}
    </section>

    <section>
      <h2>七、失败诊断建议</h2>
      {_diagnosis_panel(diagnosis)}
    </section>

    <section>
      <h2>八、页面截图证据</h2>
      {_screenshots_panel(run_dir)}
    </section>

    <section>
      <h2>九、原始证据文件</h2>
      <div class="empty">以下 JSON 仅作为审计追溯附件，正式阅读以上方可视化报告为准。</div>
      {_raw_links(run_dir)}
    </section>
  </main>
</body>
</html>
"""
    report_path = run_dir / "report.html"
    report_path.write_text(page, encoding="utf-8")
    index_path = build_report_index(run_dir.parent)
    result = StepResult(
        name="evidence_pack",
        status="SUCCESS",
        detail="可视化 HTML 闭环报告已生成",
        data={
            "report": str(report_path),
            "index": str(index_path),
            "screenshots": [str(path) for path in screenshots],
        },
    )
    write_json(run_dir / "evidence-pack.json", result.to_dict())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="生成可视化 HTML 闭环报告")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--title", default="AI 数据智造多模态闭环报告")
    args = parser.parse_args()

    build_evidence_pack(Path(args.run_dir), args.title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
