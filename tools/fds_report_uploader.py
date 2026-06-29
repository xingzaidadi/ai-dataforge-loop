#!/usr/bin/env python3
"""Optional FDS-style archive uploader for generated evidence reports.

The workshop LightReporter writes the local HTML report first, then best-effort
uploads the HTML and sibling PNG assets to FDS. This module keeps the same
failure model: local reports remain usable even if archive upload fails.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from common import StepResult, env_flag, write_json


DEFAULT_PREFIX = "reports/ai-dataforge-loop"
URL_PATTERN = re.compile(r"https?://[^\s\"']+")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _object_prefix(run_dir: Path) -> str:
    base_prefix = _env("DATAMAKE_FDS_BASE_PREFIX", DEFAULT_PREFIX).strip("/")
    date = datetime.now().strftime("%Y/%m/%d")
    return f"{base_prefix}/{date}/{run_dir.name}"


def _collect_files(run_dir: Path) -> list[tuple[Path, str]]:
    candidates = [
        run_dir / "report.html",
        run_dir / "summary.json",
        run_dir / "evidence-pack.json",
        run_dir / "params.json",
        run_dir / "screenshot-params-result.json",
        run_dir / "srm-price-clean-result.json",
        run_dir / "datamake-result.json",
        run_dir / "ui-verify-result.json",
        run_dir / "diagnosis.json",
    ]
    files: list[tuple[Path, str]] = []
    for path in candidates:
        if path.exists() and path.is_file():
            files.append((path, path.name))
    screenshot_dir = run_dir / "screenshots"
    if screenshot_dir.exists():
        for path in sorted(screenshot_dir.glob("*.png")):
            files.append((path, f"screenshots/{path.name}"))
    return files


def _format_command(template: str, file_path: Path, object_key: str, run_id: str) -> list[str]:
    command = template.format(
        file=str(file_path),
        object_key=object_key,
        run_id=run_id,
    )
    return shlex.split(command, posix=os.name != "nt")


def _extract_url(stdout: str, public_base_url: str, object_key: str) -> str:
    match = URL_PATTERN.search(stdout or "")
    if match:
        return match.group(0)
    if public_base_url:
        return f"{public_base_url.rstrip('/')}/{object_key}"
    return ""


def upload_evidence_to_fds(run_dir: Path) -> StepResult:
    enabled = env_flag("DATAMAKE_FDS_UPLOAD_ENABLED", False)
    result_path = run_dir / "fds-upload-result.json"
    if not enabled:
        result = StepResult(
            name="fds_report_upload",
            status="SKIPPED",
            detail="FDS report upload is disabled",
            data={"enabled": False},
        )
        write_json(result_path, result.to_dict())
        return result

    files = _collect_files(run_dir)
    prefix = _object_prefix(run_dir)
    dry_run = env_flag("DATAMAKE_FDS_UPLOAD_DRY_RUN", False)
    upload_command = _env("DATAMAKE_FDS_UPLOAD_COMMAND")
    public_base_url = _env("DATAMAKE_FDS_PUBLIC_BASE_URL")
    timeout = int(_env("DATAMAKE_FDS_UPLOAD_TIMEOUT_SECONDS", "60") or "60")

    if not files:
        result = StepResult(
            name="fds_report_upload",
            status="SKIPPED",
            detail="No evidence files found for FDS upload",
            data={"enabled": True, "prefix": prefix, "files": []},
        )
        write_json(result_path, result.to_dict())
        return result

    planned = [
        {
            "file": str(path),
            "objectKey": f"{prefix}/{relative_name}",
        }
        for path, relative_name in files
    ]
    if dry_run:
        result = StepResult(
            name="fds_report_upload",
            status="SKIPPED",
            detail="FDS upload dry-run: planned files only",
            data={"enabled": True, "dryRun": True, "prefix": prefix, "files": planned},
        )
        write_json(result_path, result.to_dict())
        return result

    if not upload_command:
        result = StepResult(
            name="fds_report_upload",
            status="FAILED",
            detail="DATAMAKE_FDS_UPLOAD_COMMAND is required when FDS upload is enabled",
            data={"enabled": True, "prefix": prefix, "files": planned},
        )
        write_json(result_path, result.to_dict())
        return result

    uploaded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for path, relative_name in files:
        object_key = f"{prefix}/{relative_name}"
        command = _format_command(upload_command, path, object_key, run_dir.name)
        completed = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        record = {
            "file": str(path),
            "objectKey": object_key,
            "command": command,
            "returncode": completed.returncode,
        }
        if completed.returncode == 0:
            record["url"] = _extract_url(completed.stdout, public_base_url, object_key)
            uploaded.append(record)
        else:
            record["stderr"] = completed.stderr
            record["stdout"] = completed.stdout
            failed.append(record)

    report_url = next((item.get("url") for item in uploaded if item["objectKey"].endswith("/report.html")), "")
    status = "SUCCESS" if not failed else ("PARTIAL" if uploaded else "FAILED")
    result = StepResult(
        name="fds_report_upload",
        status=status,
        detail="FDS report upload completed" if status == "SUCCESS" else "FDS report upload completed with warnings",
        data={
            "enabled": True,
            "prefix": prefix,
            "reportUrl": report_url,
            "uploaded": uploaded,
            "failed": failed,
        },
    )
    write_json(result_path, result.to_dict())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload DataForge Loop evidence report to FDS-style archive")
    parser.add_argument("--run-dir", required=True, help="evidence/runs/{run_id} directory")
    args = parser.parse_args()

    result = upload_evidence_to_fds(Path(args.run_dir))
    print(__import__("json").dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.status in {"SUCCESS", "PARTIAL", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
