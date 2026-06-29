"""
Jinja2 模板渲染
从 engine.py 原封不动提取，保证向后兼容。
"""

from pathlib import Path
from jinja2 import Template


def render_template(template_path: str, context: dict) -> str:
    """渲染 Jinja2 模板"""
    path = Path(template_path)
    if not path.exists():
        # 尝试相对于项目根目录解析
        path = Path(__file__).parent.parent / template_path
    template_content = path.read_text(encoding='utf-8')
    template = Template(template_content)
    return template.render(**context)
