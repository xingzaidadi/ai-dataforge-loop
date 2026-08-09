"""
AI 数据智造闭环引擎 — 模块化引擎库

模块拆分：
- lib.client   → MifyClient（HTTP/SQL 调用层）
- lib.resolver → 变量解析与 JSONPath 提取
- lib.renderer → Jinja2 模板渲染
- lib.flow     → FlowEngine 编排核心
- lib.config   → 配置加载器（含 use 指令展开）
"""

from .client import MifyClient
from .resolver import resolve_ref, resolve_params, extract_value
from .renderer import render_template
from .flow import FlowEngine
from .config import load_config
