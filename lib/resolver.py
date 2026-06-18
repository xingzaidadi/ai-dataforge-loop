"""
变量解析与 JSONPath 提取
从 engine.py 原封不动提取，保证向后兼容。
"""

import json
import re
from typing import Any


def resolve_ref(ref: str, context: dict) -> Any:
    """
    解析变量引用：
      {{inputs.stockOrg}}
      {{steps.get_cookie.extracted.cookie}}
      {{config.scm_base}}
      {{collected.contracts}}
    支持条件表达式：
      "{{steps.x.code}} == '0'" → True/False
    """
    if not isinstance(ref, str):
        return ref

    # 判断是否是纯引用（整个字符串就是一个 {{xxx}}）
    # 用 [^}]+ 而非 .+? 避免匹配到跨多个引用的内容
    pure_match = re.match(r'^\{\{([^}]+)\}\}$', ref.strip())
    if pure_match:
        return _resolve_expr(pure_match.group(1).strip(), context)

    # 字符串中包含多个引用，做替换
    def replacer(m):
        val = _resolve_expr(m.group(1).strip(), context)
        return str(val) if val is not None else ""

    return re.sub(r'\{\{(.+?)\}\}', replacer, ref)


def _resolve_expr(expr: str, context: dict) -> Any:
    """解析单个表达式，支持 ==, !=, ||, &&"""

    def _none_safe_eq(left_val, right_val):
        if left_val is None:
            return right_val is None or right_val == '' or right_val == 'None'
        if right_val is None or right_val == '':
            return left_val is None or str(left_val) == ''
        return str(left_val) == str(right_val)

    def _none_safe_neq(left_val, right_val):
        return not _none_safe_eq(left_val, right_val)

    # 先检查是否包含逻辑运算符
    if "||" in expr:
        parts = expr.split("||")
        return any(_resolve_expr(p.strip(), context) for p in parts)
    if "&&" in expr:
        parts = expr.split("&&")
        return all(_resolve_expr(p.strip(), context) for p in parts)

    # 处理条件表达式中的 == 和 !=
    if "==" in expr:
        left, right = expr.split("==", 1)
        left_val = _resolve_path(left.strip(), context)
        right_val = right.strip().strip("'\"")
        return _none_safe_eq(left_val, right_val)
    if "!=" in expr:
        left, right = expr.split("!=", 1)
        left_val = _resolve_path(left.strip(), context)
        right_val = right.strip().strip("'\"")
        return _none_safe_neq(left_val, right_val)

    return _resolve_path(expr, context)


def _resolve_path(path: str, context: dict) -> Any:
    """
    解析点分+方括号路径：
      steps.get_cookie.extracted.cookie
      inputs.materials[context.mat_key]
      inputs.materials[materialCode1]
    """
    # 用正则把 path 拆成 segments
    segments = []
    i = 0
    while i < len(path):
        if path[i] == '.':
            i += 1
            continue
        elif path[i] == '[':
            # 找到匹配的 ]
            j = path.index(']', i)
            bracket_content = path[i+1:j].strip().strip("'\"")
            segments.append(('bracket', bracket_content))
            i = j + 1
        else:
            # 找到下一个 . 或 [
            j = i
            while j < len(path) and path[j] not in '.[':
                j += 1
            segments.append(('dot', path[i:j]))
            i = j

    current = context
    for seg_type, seg_val in segments:
        if current is None:
            return None
        if seg_type == 'dot':
            if isinstance(current, dict):
                current = current.get(seg_val)
            elif isinstance(current, list) and seg_val.isdigit():
                idx = int(seg_val)
                current = current[idx] if idx < len(current) else None
            else:
                return None
        elif seg_type == 'bracket':
            # 方括号里的内容可能是变量引用（如 context.mat_key）或字面量
            # 先尝试作为 context 变量解析
            resolved_key = _resolve_path(seg_val, context)
            if resolved_key is None:
                # 不是变量，当字面量用
                resolved_key = seg_val
            if isinstance(current, dict):
                current = current.get(str(resolved_key))
            elif isinstance(current, list):
                try:
                    idx = int(resolved_key)
                    current = current[idx] if idx < len(current) else None
                except (ValueError, TypeError):
                    return None
            else:
                return None

    return current


def resolve_params(params: Any, context: dict) -> Any:
    """递归解析参数中的所有变量引用"""
    if params is None:
        return None
    if isinstance(params, str):
        return resolve_ref(params, context)
    if isinstance(params, (int, float, bool)):
        return params
    if isinstance(params, list):
        return [resolve_params(item, context) for item in params]
    if isinstance(params, dict):
        return {k: resolve_params(v, context) for k, v in params.items()}
    return params


def extract_value(data: Any, path: str) -> Any:
    """
    从返回数据中提取值（简易 JSONPath）
    支持: $.body.code, $.rows[0].purchase_no, $.body.data.result.cookie
    自动处理 body 为 JSON 字符串的情况
    """
    if not path or path == "$":
        return data

    path = path.lstrip("$.")
    parts = re.split(r'\.(?![^\[]*\])', path)
    current = data

    # 如果 data 的 body 是字符串且 path 以 body 开头，先 parse body
    if isinstance(data, dict) and isinstance(data.get("body"), str) and parts and parts[0] == "body":
        try:
            data["body"] = json.loads(data["body"])
            current = data
        except (json.JSONDecodeError, TypeError):
            pass

    for part in parts:
        if current is None:
            return None
        match = re.match(r'(\w+)\[(\d+)\]', part)
        if match:
            key, idx = match.group(1), int(match.group(2))
            current = current.get(key, []) if isinstance(current, dict) else []
            current = current[idx] if isinstance(current, list) and idx < len(current) else None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None

    return current
