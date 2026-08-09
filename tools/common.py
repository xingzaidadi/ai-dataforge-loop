#!/usr/bin/env python3
"""Shared helpers for multimodal closed-loop runners."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "evidence" / "runs"


SENSITIVE_PATTERNS = [
    (re.compile(r"app-[A-Za-z0-9]{12,}"), "app-***"),
    (re.compile(r"mysql\+pymysql:/{2}[^@\s]+@"), "mysql+pymysql://${DB_USER}:${DB_PASSWORD}@"),
    (re.compile(r"https?://[^\s\"']*mioffice\.cn[^\s\"']*"), "${INTERNAL_MIOFFICE_URL}"),
    (re.compile(r"https?://[^\s\"']*toolskit\.test\.mi\.com[^\s\"']*"), "${INTERNAL_TOOLSKIT_URL}"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE), "Bearer ***"),
    # Cookie 值：匹配 "Cookie: xxx"、'Cookie': 'xxx'、cookie=xxx（到行尾/引号/分号止）
    (re.compile(r"(['\"]?[Cc]ookie['\"]?\s*[:=]\s*['\"]?)[^'\"\n;]+"), r"\1***"),
]


def now_compact() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def make_run_id(prefix: str = "DATAMAKE") -> str:
    return f"{prefix}-{now_compact()}"


def ensure_run_dir(run_id: str) -> Path:
    run_dir = EVIDENCE_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def sanitize_text(value: str) -> str:
    sanitized = value
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def sanitize_data(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [sanitize_data(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_data(item) for key, item in value.items()}
    return value


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize_data(data), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_kv_pairs(values: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"参数必须是 key=value 格式: {raw}")
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"参数 key 不能为空: {raw}")
        try:
            parsed[key] = json.loads(value)
        except json.JSONDecodeError:
            parsed[key] = value
    return parsed


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class StepResult:
    name: str
    status: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "data": self.data,
        }
