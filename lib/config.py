"""
配置加载器 — 读取 YAML 配置、展开环境变量与 use 指令
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml

from .flow import FlowEngine, _resolve_use_ref


def load_config(config_path: str, shared_dir: str = "") -> dict:
    """
    加载场景配置文件，自动展开 use 指令。

    如果配置包含 use 引用，会从 shared/ 目录加载对应的共享步骤定义。
    """
    path = Path(config_path)
    if not path.exists():
        path = Path(__file__).parent.parent / config_path
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config = expand_env(config)

    # 如果没有 use 指令，直接返回
    if not config.get("use") and not _has_inline_use(config.get("steps", [])):
        return config

    # 加载共享步骤定义
    project_root = Path(__file__).parent.parent
    if shared_dir:
        shared_path = Path(shared_dir)
    else:
        shared_path = project_root / "shared"

    shared_steps = _load_shared_steps(shared_path)

    # 展开 use 指令
    config = FlowEngine.expand_use(config, shared_steps)
    config = expand_env(config)
    return config


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")


def expand_env(value: Any) -> Any:
    """
    递归展开配置中的环境变量占位符。

    支持:
      ${MIFY_TOKEN}
      ${MIFY_USER:-skill-runner}

    未设置且无默认值时保留原占位符，便于校验脚本给出提示。
    """
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    if not isinstance(value, str):
        return value

    def repl(match):
        name = match.group(1)
        default = match.group(2)
        current = os.environ.get(name)
        if current is not None:
            return current
        if default is not None:
            return default
        return match.group(0)

    return _ENV_PATTERN.sub(repl, value)


def _has_inline_use(steps: list) -> bool:
    """检查步骤列表中是否包含内联 use 指令"""
    for step in steps:
        if isinstance(step, dict) and "use" in step:
            return True
    return False


def _load_shared_steps(shared_dir: Path) -> dict:
    """
    从 shared/ 目录加载所有共享步骤定义。

    支持两种文件组织方式：
    1. shared/common-steps.yaml — 单文件，common_steps 顶层 key
    2. shared/*.yaml — 多文件，每个文件的 common_steps 顶层 key 合并
    """
    shared_steps = {}

    if not shared_dir.exists():
        return shared_steps

    for yaml_file in shared_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                # 支持 common_steps 顶层 key
                steps = data.get("common_steps", {})
                if isinstance(steps, dict):
                    shared_steps.update(steps)
        except Exception as e:
            print(f"  ⚠️ 加载共享步骤失败 {yaml_file}: {e}")

    return shared_steps


def load_mify_config(config_path: str = "") -> dict:
    """加载 mify 端点配置"""
    if not config_path:
        config_path = str(Path(__file__).parent.parent / "configs" / "mify-endpoint.yaml")
    path = Path(config_path)
    if path.exists():
        return expand_env(yaml.safe_load(path.read_text(encoding='utf-8')) or {})
    return {}
