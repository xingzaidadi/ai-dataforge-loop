"""
FlowEngine 编排核心 — 执行步骤、条件分支、循环、路由
从 engine.py 搬迁，新增：use 指令支持、状态快照、改进错误处理。
"""

import json
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Optional

# 强制行缓冲，确保每步输出实时可见
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

# 详细调试输出（完整请求体、SQL 全量行、headers 等）默认关闭——
# 这些内容会被 datamake_runner 抓进证据包，含业务字段/Cookie，属敏感信息。
# 需排障时设 DATAFORGE_DEBUG=1 开启。
_DEBUG = os.environ.get("DATAFORGE_DEBUG", "").strip() not in ("", "0", "false", "False")

from .resolver import resolve_ref, resolve_params, extract_value
from .renderer import render_template


class FlowEngine:
    """通用编排引擎：读 YAML → 调 mify → 解析返回 → 条件分支/循环"""

    def __init__(self, config: dict, inputs: dict, mify, progress_callback=None):
        self.config = config
        self.inputs = inputs
        self.mify = mify
        self.cookie = ""
        self.progress_callback = progress_callback  # 进度回调函数
        self.goto_count = {}  # 记录每个步骤的 goto 次数，防止无限循环
        self.max_goto = 10   # 单步最大循环次数
        self.baseline_pr_no = None  # 兼容旧引用
        self.baseline_pr_id = None   # PR 创建前的最大 id，用于过滤旧记录
        self.state_file: Optional[Path] = None  # 状态快照文件路径
        self.context = {
            "config": config.get("config", {}),
            "inputs": inputs,
            "steps": {},
            "collected": {},
            "context": {},
        }
        self.steps_map = {s["id"]: s for s in config.get("steps", [])}
        self.terminals = config.get("terminals", {})

    # ──────────────────────────────────────────────
    #  use 指令展开
    # ──────────────────────────────────────────────

    @staticmethod
    def expand_use(config: dict, shared_steps: dict) -> dict:
        """
        展开配置中的 use 指令。

        两种级别：
        1. 顶层 config.use = ["common-steps.get_cookie", ...]
           → 把这些共享步骤插入到 config.steps 的开头
        2. 步骤列表中 - use: common-steps.check_asl
           → 把这个引用替换为共享步骤的定义

        shared_steps 格式：{step_id: step_dict}
        """
        steps = list(config.get("steps", []))
        expanded = []

        # 1. 顶层 use 展开：预置到 steps 开头
        top_use = config.get("use", [])
        if top_use:
            for ref in top_use:
                step_def = _resolve_use_ref(ref, shared_steps)
                if step_def:
                    expanded.append(step_def)
                else:
                    print(f"  ⚠️ use 引用未找到: {ref}")

        # 2. 步骤级 use 展开
        for step in steps:
            if isinstance(step, dict) and "use" in step:
                ref = step["use"]
                step_def = _resolve_use_ref(ref, shared_steps)
                if step_def:
                    # 支持覆盖：merge step 中非 use 的字段
                    override = {k: v for k, v in step.items() if k != "use"}
                    if override:
                        merged = {**step_def, **override}
                        expanded.append(merged)
                    else:
                        expanded.append(step_def)
                else:
                    print(f"  ⚠️ use 引用未找到: {ref}")
            else:
                expanded.append(step)

        result = dict(config)
        result["steps"] = expanded
        return result

    # ──────────────────────────────────────────────
    #  进度通知
    # ──────────────────────────────────────────────

    def _notify_progress(self, step_id: str, status: str, detail: str = ""):
        """发送进度通知（通过回调函数）"""
        if self.progress_callback:
            try:
                self.progress_callback(step_id, status, detail)
            except Exception:
                pass  # 通知失败不影响流程

    # ──────────────────────────────────────────────
    #  执行入口
    # ──────────────────────────────────────────────

    def run(self, save_state: bool = False, state_file: str = ""):
        """执行流程"""
        if save_state or state_file:
            self.state_file = Path(state_file) if state_file else Path(".state.json")
            self._load_state()

        steps = self.config.get("steps", [])
        if not steps:
            print("❌ 没有步骤定义")
            return

        idx = 0
        while idx < len(steps):
            step = steps[idx]
            step_id = step["id"]
            action = step.get("action")

            print(f"\n{'='*50}")
            print(f"▶ {step_id} ({action})")
            print(f"{'='*50}")
            self._notify_progress(step_id, "start")
            t_start = time.time()

            try:
                next_target = self.execute_step(step)
                elapsed = time.time() - t_start
                self._notify_progress(step_id, "done", f"{elapsed:.1f}s")
            except Exception as e:
                elapsed = time.time() - t_start
                self._notify_progress(step_id, "error", f"{elapsed:.1f}s {str(e)[:80]}")
                self._print_error_context(step_id, e)
                raise

            # 保存状态快照
            if self.state_file:
                self._save_state()

            # 检查终止节点
            if next_target in self.terminals:
                terminal = self.terminals[next_target]
                msg = resolve_ref(terminal.get("message", ""), self.context)
                if terminal["type"] == "success":
                    print(f"\n✅ {msg}")
                else:
                    print(f"\n❌ {msg}")
                return

            if next_target:
                # 跳转到指定步骤（带循环保护）
                self.goto_count[next_target] = self.goto_count.get(next_target, 0) + 1
                if self.goto_count[next_target] > self.max_goto:
                    print(f"\n❌ 检测到无限循环：{next_target} 已跳转 {self.goto_count[next_target]} 次，强制终止")
                    return
                print(f"  🔄 跳转 to {next_target} (第 {self.goto_count[next_target]} 次)")

                found = False
                for i, s in enumerate(steps):
                    if s["id"] == next_target:
                        idx = i
                        found = True
                        break
                if not found:
                    print(f"❌ 找不到步骤: {next_target}")
                    return
            else:
                idx += 1

        print("\n✅ 流程执行完毕")

    # ──────────────────────────────────────────────
    #  状态快照（支持中断恢复）
    # ──────────────────────────────────────────────

    def _save_state(self):
        """保存当前上下文到 .state.json"""
        if not self.state_file:
            return
        try:
            state = {
                "cookie": self.cookie,
                "goto_count": self.goto_count,
                "baseline_pr_id": self.baseline_pr_id,
                "context": {
                    "config": self.context.get("config", {}),
                    "inputs": self.context.get("inputs", {}),
                    "steps": self.context.get("steps", {}),
                    "collected": self.context.get("collected", {}),
                    "context": self.context.get("context", {}),
                },
            }
            self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str))
        except Exception:
            pass  # 静默失败，不影响流程

    def _load_state(self):
        """从 .state.json 恢复状态"""
        if not self.state_file or not self.state_file.exists():
            return
        try:
            state = json.loads(self.state_file.read_text(encoding='utf-8'))
            self.cookie = state.get("cookie", self.cookie)
            self.goto_count = state.get("goto_count", {})
            self.baseline_pr_id = state.get("baseline_pr_id")
            ctx = state.get("context", {})
            if ctx:
                self.context["steps"] = ctx.get("steps", {})
                self.context["collected"] = ctx.get("collected", {})
                self.context["context"] = ctx.get("context", {})
            print(f"  📦 已从 {self.state_file} 恢复状态")
        except Exception as e:
            print(f"  ⚠️ 状态恢复失败: {e}")

    # ──────────────────────────────────────────────
    #  改进的错误处理
    # ──────────────────────────────────────────────

    def _print_error_context(self, step_id: str, error: Exception):
        """步骤失败时打印完整上下文"""
        print(f"\n❌ 步骤 [{step_id}] 执行异常: {error}")
        print(f"  📋 已解析变量:")
        for key, val in self.context.items():
            if key == "config":
                continue
            if isinstance(val, dict):
                for k2, v2 in val.items():
                    display = str(v2)[:80] if v2 is not None else "None"
                    print(f"    {key}.{k2} = {display}")
            else:
                display = str(val)[:80] if val is not None else "None"
                print(f"    {key} = {display}")

    # ──────────────────────────────────────────────
    #  步骤调度
    # ──────────────────────────────────────────────

    def execute_step(self, step: dict) -> str:
        """执行单个步骤，返回 goto 目标或 None（顺序执行）"""
        action = step.get("action")
        step_id = step["id"]

        # 注：baseline_pr_id 曾在 create_pr 前查一次 MAX(id) 存基准，但全代码库无任何
        # 地方读取它做过滤（query_pr_info 用 status>=10 ORDER BY id DESC LIMIT 1 定位），
        # 属死代码且每次多一次 mify 往返。已移除该调用；属性保留以兼容旧 state 文件。

        # 如果是 get_cookie 步骤且 cookie 已获取，跳过执行
        if step_id == "get_cookie" and self.cookie:
            print(f"  ⏭️ 跳过 get_cookie（cookie 已获取，长度: {len(self.cookie)}）")
            self.context["steps"][step_id] = {"extracted": {"cookie": self.cookie}}
            return step.get("goto")

        action_map = {
            "http_call": self._do_http_call,
            "sql_query": self._do_sql_query,
            "template": self._do_template,
            "condition": self._do_condition,
            "switch": self._do_switch,
            "loop": self._do_loop,
            "route": self._do_route,
            "sql_execute": self._do_sql_execute,
            "filter_collection": self._do_filter_collection,
            "noop": self._do_noop,
        }

        handler = action_map.get(action)
        if handler:
            return handler(step)
        else:
            print(f"  ⚠️ 未知 action: {action}")
            return None

    # ──────────────────────────────────────────────
    #  HTTP 调用
    # ──────────────────────────────────────────────

    def _set_baseline_pr(self):
        """在创建 PR 前记录当前最大的 id，用于后续过滤旧记录"""
        db_uri = self.context.get("config", {}).get("db_uri", "")
        stock_org = self.inputs.get("stockOrg", "")
        if not db_uri or not stock_org:
            return
        query = f"SELECT MAX(id) as max_id FROM m_purchase WHERE stock_org='{stock_org}'"
        result = self.mify.sql_query(db_uri, query)
        rows = result.get("rows", [])
        if rows:
            max_id = rows[0].get("max_id")
            if max_id:
                self.baseline_pr_id = int(max_id)
                print(f"  📌 baseline_pr_id = {self.baseline_pr_id}")

    def _do_http_call(self, step: dict) -> str:
        """执行 HTTP 调用（通过 mify）"""
        # 暴露一个每次调用刷新的秒级时间戳，供需要 cache-buster/key 的接口引用
        # （如 SRM po/close、po/open 的 key 参数）。用 {{now_ts}} 引用。
        self.context["now_ts"] = str(int(time.time()))
        params = resolve_params(step.get("params", {}), self.context)

        url = params.get("url") or ""
        method = params.get("method", "get")
        body = params.get("body", "")

        # query-string 参数（SRM sourcing-data / srm-tools 等接口要求 query 而非 JSON body）
        # 用法：params.query: {query_table: ZV_PO, ...}，urlencode 后拼到 URL
        query = params.get("query")
        if isinstance(query, dict) and query:
            qs = urllib.parse.urlencode({k: ("" if v is None else str(v)) for k, v in query.items()})
            url = url + ("&" if "?" in url else "?") + qs

        # body 如果是 dict/list，转成 JSON 字符串
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)

        # 处理 headers：支持字符串格式 "Cookie: xxx" 转换为 JSON 对象格式
        headers_input = params.get("headers", "")
        headers_obj = {}
        if headers_input:
            if isinstance(headers_input, dict):
                headers_obj = headers_input
            elif isinstance(headers_input, str):
                # 解析 "Key: Value\nKey2: Value2" 格式
                for line in headers_input.split("\n"):
                    if ":" in line:
                        key, val = line.split(":", 1)
                        headers_obj[key.strip()] = val.strip()
        # 如果 headers 中有 Cookie，提取到 cookie 参数（mify workflow 只认 inputs.cookie）
        if "Cookie" in headers_obj:
            cookie_from_header = headers_obj.pop("Cookie")
            if cookie_from_header:
                self.cookie = cookie_from_header
        if _DEBUG:
            print(f"  🔍 headers_obj: {headers_obj}")  # DEBUG（含 Cookie，默认关闭）

        wait = step.get("wait", 0)
        if wait:
            print(f"  ⏳ 等待 {wait} 秒...")
            time.sleep(wait)

        retry_config = step.get("retry", {})
        max_retries = retry_config.get("max", 1)
        interval_ms = retry_config.get("interval_ms", 100)

        result = None
        for attempt in range(max_retries):
            print(f"  📡 {method.upper()} {url[:80]}{'...' if len(url)>80 else ''}")

            result = self.mify.http_call(
                url=url,
                method=method,
                body=body,
                cookie=self.cookie,
                headers=headers_obj,
            )
            # DEBUG: 打印 result（含完整响应/请求体，默认关闭，设 DATAFORGE_DEBUG=1 开启）
            if _DEBUG and ("get_cookie" in step.get("id", "") or "create_pr" in step.get("id", "")):
                print(f"  📍 result: {json.dumps(result, ensure_ascii=False)[:2000]}")
            if _DEBUG and "create_pr" in step.get("id", ""):
                print(f"  🔴 create_pr full body: {json.dumps(result.get('body', ''), ensure_ascii=False)}")
                print(f"  🔴 create_pr request body length: {len(body)}")
                print(f"  🔴 create_pr request body (first 3000): {body[:3000]}")

            # datacube 场景接口：无条件打印原始返回体，用于核实 commandCode/zasnNo
            # 到底是「接口没回」还是「回了但我们抽取路径没对上」。历史误判为「mify 丢体」，
            # 实为从未打印过原始 body。scene/execute 与 executeRecordLog 都覆盖。
            if "scene/execute" in url or "executeRecordLog" in url or "scene/scene" in url:
                _raw = result.get("body", "")
                _raws = json.dumps(_raw, ensure_ascii=False) if not isinstance(_raw, str) else _raw
                print(f"  🧪 datacube 原始返回 status={result.get('status_code')} bodyType={type(_raw).__name__} len={len(_raws)}")
                print(f"  🧪 datacube body[:2500]: {_raws[:2500]}")

            # 检测 mify 平台限制：非 2xx 响应 body 为空
            resp_status = result.get("status_code", 0)
            resp_body = result.get("body", {})
            if resp_status >= 400 and isinstance(resp_body, dict) and resp_body.get("_error"):
                print(f"  ❌ HTTP {resp_status} 错误: {resp_body.get('_error', '')}")
                self.context["steps"][step["id"]] = {
                    "result": result,
                    "extracted": {k: None for k in step.get("extract", {}).keys()},
                }
                raise Exception(f"HTTP {resp_status}: {resp_body.get('_error', '响应体为空')}")

            # 提取字段（支持变量引用和 JSONPath）
            extracted = {}
            for key, path in step.get("extract", {}).items():
                if isinstance(path, str) and "{{" in path:
                    extracted[key] = resolve_ref(path, self.context)
                else:
                    extracted[key] = extract_value(result, path)

            self.context["steps"][step["id"]] = {
                "result": result,
                "extracted": extracted,
            }

            # 检查是否需要重试（提取的 code 不为 0 且还有重试次数）
            code = extracted.get("code")
            has_error = step.get("on_error")
            # 只有当 code 明确存在且不为 '0' 时才重试
            if has_error and code is not None and str(code) != "0" and attempt < max_retries - 1:
                print(f"  🔄 重试 {attempt + 1}/{max_retries}，等待 {interval_ms}ms")
                time.sleep(interval_ms / 1000)
                continue
            # 如果有错误且不再重试，显示错误信息
            if has_error and code is not None and str(code) != "0":
                error_msg = step.get("on_error", {}).get("message", "未知错误")
                print(f"  ❌ 错误: {error_msg}")
            break

        # 打印提取结果
        extracted = self.context["steps"][step["id"]]["extracted"]
        for k, v in extracted.items():
            v_display = str(v)[:100] if v is not None else "None"
            print(f"  📌 {k} = {v_display}")

        # 尊重步骤上声明的 goto（历史缺陷：此处曾无条件 return None，
        # 导致 http_call 的 goto 被静默忽略，引擎退化为顺序执行；一旦 goto
        # 目标非相邻步骤即静默跑错分支。无 goto 时返回 None 保持顺序执行不变）。
        return step.get("goto")

    # ──────────────────────────────────────────────
    #  SQL 查询
    # ──────────────────────────────────────────────

    def _do_sql_query(self, step: dict) -> str:
        """执行 SQL 查询（通过 mify SQL 工作流），支持重试"""
        wait = step.get("wait", 0)
        if wait:
            print(f"  ⏳ 等待 {wait} 秒...")
            time.sleep(wait)

        retry_config = step.get("retry", {})
        max_retries = retry_config.get("max", 1)
        interval_ms = retry_config.get("interval_ms", 1000)

        # 预处理：自动从 inputs 生成常用变量（materials_sql_in, project_filter）
        inputs = self.context.get("inputs", {})
        materials = inputs.get("materials", {})
        if isinstance(materials, dict) and materials:
            codes = [f"'{v}'" for v in materials.values()]
            self.context["materials_sql_in"] = ",".join(codes)
        else:
            self.context["materials_sql_in"] = "''"

        # 预处理：从自动获取的物料行生成 auto_materials_sql_in 和 auto_supplier_code
        # 支持两种 step id：auto_get_materials 和 extract_materials
        auto_rows = (
            self.context.get("steps", {}).get("extract_materials", {}).get("extracted", {}).get("materials_rows", [])
            or self.context.get("steps", {}).get("auto_get_materials", {}).get("extracted", {}).get("materials_rows", [])
        )
        if auto_rows:
            auto_codes = [f"'{r['xm_code']}'" for r in auto_rows if r.get("xm_code")]
            self.context["auto_materials_sql_in"] = ",".join(auto_codes) if auto_codes else "''"
            self.context["auto_supplier_code"] = auto_rows[0].get("supplier_code", "")
        else:
            self.context.setdefault("auto_materials_sql_in", "''")
            self.context.setdefault("auto_supplier_code", "")

        project_code = inputs.get("projectCode", "")
        if project_code:
            self.context["project_filter"] = f"AND mp.project_code = '{project_code}'"
        else:
            self.context["project_filter"] = ""

        # 现在 resolve_params 会正确找到 materials_sql_in
        params = resolve_params(step.get("params", {}), self.context)

        db_uri = params.get("db_uri", "")
        query = params.get("query", "").strip()

        result = {"rows": [], "_raw": ""}
        for attempt in range(max_retries):
            if not db_uri or not query:
                print(f"  ⚠️ 缺少 db_uri 或 query，跳过")
                break

            print(f"  🗄️ SQL: {query[:120]}{'...' if len(query)>120 else ''}")
            if attempt > 0:
                print(f"  🔍 DEBUG db_uri: {db_uri}")
                print(f"  🔍 DEBUG query: {query}")

            result = self.mify.sql_query(db_uri, query)
            if attempt > 0:
                print(f"  🔍 MIFY RESULT: {result}")

            if result.get("_error"):
                print(f"  ❌ SQL执行失败: {result['_error']}")
                break

            rows = result.get("rows", [])

            if rows or attempt >= max_retries - 1:
                print(f"  ✅ 查询完成，返回 {len(rows)} 行{'(重试后)' if attempt > 0 else ''}")
                break

            print(f"  🔄 重试 {attempt + 1}/{max_retries}，等待 {interval_ms}ms...")
            time.sleep(interval_ms / 1000)

        # 过滤：如果步骤配了 filter，则只保留匹配的行
        filter_conf = step.get("filter")
        if filter_conf and result.get("rows"):
            filter_field = filter_conf.get("field")
            filter_source = filter_conf.get("source")  # 如 "inputs.materials"
            if filter_field and filter_source:
                allowed = set()
                src_val = resolve_ref("{{" + filter_source + "}}", self.context)
                if isinstance(src_val, dict):
                    allowed = set(src_val.values())
                elif isinstance(src_val, list):
                    # 列表可能是字典列表（如 materials_rows），需要提取 filter_field 对应的值
                    if src_val and isinstance(src_val[0], dict):
                        allowed = set(item.get(filter_field, "") for item in src_val if item.get(filter_field))
                    else:
                        allowed = set(src_val)
                if allowed:
                    before = len(result["rows"])
                    result["rows"] = [
                        r for r in result["rows"]
                        if r.get(filter_field) in allowed
                    ]
                    print(f"  🔍 过滤: {filter_field} in {allowed} → {before}行 → {len(result['rows'])}行")

        extracted = {}
        for key, path in step.get("extract", {}).items():
            # 先检查是否是变量引用（如 {{context.pr_item.id}}），如果是则用 resolve_ref
            if isinstance(path, str) and "{{" in path:
                extracted[key] = resolve_ref(path, self.context)
            else:
                val = extract_value(result, path)
                if _DEBUG:
                    print(f"  🔍 DEBUG extract: key={key}, path={path}, result_rows={result.get('rows', [])}, val={val!r}")
                extracted[key] = val

        self.context["steps"][step["id"]] = {
            "result": result,
            "extracted": extracted,
        }

        # 打印提取结果
        for k, v in extracted.items():
            v_display = str(v)[:100] if v is not None else "None"
            print(f"  📌 {k} = {v_display}")

        return None

    def _do_sql_execute(self, step: dict) -> str:
        """执行 SQL 写操作（INSERT/UPDATE/DELETE），不走重试逻辑"""
        wait = step.get("wait", 0)
        if wait:
            print(f"  ⏳ 等待 {wait} 秒...")
            time.sleep(wait)

        params = resolve_params(step.get("params", {}), self.context)

        db_uri = params.get("db_uri", "")
        query = params.get("query", "").strip()

        if not db_uri or not query:
            print(f"  ⚠️ 缺少 db_uri 或 query，跳过")
            result = {"rows": [], "_raw": ""}
        else:
            print(f"  ⚡ SQL Execute: {query[:120]}{'...' if len(query)>120 else ''}")

            result = self.mify.sql_query(db_uri, query)

            if result.get("_error"):
                print(f"  ❌ SQL执行失败: {result['_error']}")
            else:
                raw = result.get("_raw", "")
                print(f"  ✅ 执行完成 {raw}")

        step_id = step["id"]
        self.context["steps"][step_id] = {
            "result": result,
            "extracted": {"affected": result.get("_raw", "").replace("affected: ", "") if result.get("_raw") else "0"},
        }
        return None

    # ──────────────────────────────────────────────
    #  集合过滤
    # ──────────────────────────────────────────────

    def _do_filter_collection(self, step: dict) -> str:
        """过滤集合：从某步骤的 extracted 数据中筛选匹配 inputs 的记录"""
        source_ref = step.get("source", "")  # 如 "steps.fetch_materials.extracted.materials_data"
        match_field = step.get("match_field", "materialCode")  # 集合中用于匹配的字段名
        input_ref = step.get("input_ref", "inputs.materials")  # 用户输入的物料 dict
        output_key = step.get("output_key", "filtered")

        # 获取源数据
        source_data = resolve_ref("{{" + source_ref + "}}", self.context)
        input_val = resolve_ref("{{" + input_ref + "}}", self.context)

        # 提取用户指定的物料编码（dict 的 value 是物料编码，key 是通用名称）
        if isinstance(input_val, dict):
            allowed = set(input_val.values())
        elif isinstance(input_val, list):
            allowed = set(input_val)
        else:
            allowed = {str(input_val)}

        # 过滤
        if isinstance(source_data, list):
            filtered = [item for item in source_data if item.get(match_field, "") in allowed]
        else:
            filtered = source_data

        print(f"  🔍 filter_collection: {len(source_data) if isinstance(source_data, list) else '?'} → {len(filtered) if isinstance(filtered, list) else '?'} 条 (匹配 {allowed})")

        self.context["steps"][step["id"]] = {
            "output": filtered,
            "extracted": {output_key: filtered}
        }
        return None

    # ──────────────────────────────────────────────
    #  空操作
    # ──────────────────────────────────────────────

    def _do_noop(self, step: dict) -> str:
        """空操作（占位符，用于 condition 分支）"""
        print(f"  ⏭️ noop: {step.get('id', '<no id>')}")
        self.context["steps"][step["id"]] = {"output": None, "extracted": {}}
        return step.get("goto")

    # ──────────────────────────────────────────────
    #  模板渲染
    # ──────────────────────────────────────────────

    def _do_template(self, step: dict) -> str:
        """渲染 Jinja2 模板"""
        template_path = step.get("template", "")
        ctx = resolve_params(step.get("context", {}), self.context)
        # DEBUG（渲染上下文含业务字段，默认关闭，设 DATAFORGE_DEBUG=1 开启）
        if _DEBUG:
            print(f"  🔧 ENGINE inputs keys: {list(self.context.get('inputs', {}).keys())}")
            print(f"  🔧 ENGINE inputs.materials: {str(self.context.get('inputs', {}).get('materials', 'MISSING'))[:100]}")
            for k, v in (ctx or {}).items():
                print(f"  🔧 ctx: {k} = {str(v)[:100]}")
        output = render_template(template_path, ctx)
        self.context["steps"][step["id"]] = {"output": output}
        print(f"  📝 模板渲染完成，长度: {len(output)}")
        return None

    # ──────────────────────────────────────────────
    #  条件分支
    # ──────────────────────────────────────────────

    def _do_condition(self, step: dict) -> str:
        """条件分支"""
        if_expr = step.get("if", "false")

        # 优先：尝试作为完整条件表达式解析（如 "{{x.code}} == '0'"）
        # 先提取所有 {{}} 引用，解析值，再做比较
        result = self._eval_condition_expr(if_expr)
        is_true = bool(result)
        print(f"  🔀 if: {if_expr} → {result} → {'✅ then' if is_true else '❌ else'}")
        return step.get("then") if is_true else step.get("else")

    def _eval_condition_expr(self, expr: str) -> Any:
        """解析条件表达式，支持 ==, !=, ||, &&，None 与空字符串互认"""
        import re as _re

        # 空值等价集合：None、空串、字面量 'None'/'null'（YAML 里写 == null 会被
        # 当作字符串右值，DB 也可能存字符串 "null"）——统一视作"空"。
        _EMPTY = {'', 'None', 'null'}

        def _is_empty(v):
            return v is None or (isinstance(v, str) and v.strip() in _EMPTY) or str(v) in _EMPTY

        def _none_safe_eq(left_val, right_val):
            if _is_empty(left_val) or _is_empty(right_val):
                return _is_empty(left_val) and _is_empty(right_val)
            return str(left_val) == str(right_val)

        def _none_safe_neq(left_val, right_val):
            return not _none_safe_eq(left_val, right_val)

        def _eval_single(single_expr: str) -> Any:
            """解析单个比较表达式"""
            single_expr = single_expr.strip()
            # contains：子串包含判断（左值包含右值字面量）
            # 用于如 "{{inputs.priceType}} contains 'machine_fee'"
            m = _re.match(r'^(.+?)\s+contains\s+(.+)$', single_expr)
            if m:
                left_raw = m.group(1).strip()
                right_raw = m.group(2).strip().strip("'\"")
                left_val = resolve_ref(left_raw, self.context)
                if right_raw.startswith("{{") and right_raw.endswith("}}"):
                    right_val = resolve_ref(right_raw, self.context)
                else:
                    right_val = right_raw
                if left_val is None or right_val is None:
                    return False
                return str(right_val) in str(left_val)
            if "==" in single_expr:
                m = _re.match(r'^(.+?)\s*==\s*(.+)$', single_expr)
                if m:
                    left_raw = m.group(1).strip()
                    right_raw = m.group(2).strip().strip("'\"")
                    left_val = resolve_ref(left_raw, self.context)
                    if right_raw.startswith("{{") and right_raw.endswith("}}"):
                        right_val = resolve_ref(right_raw, self.context)
                    else:
                        right_val = right_raw
                    return _none_safe_eq(left_val, right_val)
            if "!=" in single_expr:
                m = _re.match(r'^(.+?)\s*!=\s*(.+)$', single_expr)
                if m:
                    left_raw = m.group(1).strip()
                    right_raw = m.group(2).strip().strip("'\"")
                    left_val = resolve_ref(left_raw, self.context)
                    if right_raw.startswith("{{") and right_raw.endswith("}}"):
                        right_val = resolve_ref(right_raw, self.context)
                    else:
                        right_val = right_raw
                    return _none_safe_neq(left_val, right_val)
            return resolve_ref(single_expr, self.context)

        # 先检查是否包含 || 或 && 逻辑运算符
        if "||" in expr:
            parts = expr.split("||")
            return any(_eval_single(p) for p in parts)
        if "&&" in expr:
            parts = expr.split("&&")
            return all(_eval_single(p) for p in parts)

        # 单个表达式
        return _eval_single(expr)

    # ──────────────────────────────────────────────
    #  多路分支
    # ──────────────────────────────────────────────

    def _do_switch(self, step: dict) -> str:
        """多路分支"""
        switch_val = resolve_ref(step.get("switch_on", ""), self.context)
        for case in step.get("cases", []):
            match = case.get("match", [])
            if isinstance(match, str):
                match = [match]
            if str(switch_val) in match:
                print(f"  🔀 switch({switch_val}) → 匹配 {match} → {case['goto']}")
                return case["goto"]
        default = step.get("default")
        print(f"  🔀 switch({switch_val}) → default → {default}")
        return default

    # ──────────────────────────────────────────────
    #  循环
    # ──────────────────────────────────────────────

    def _do_loop(self, step: dict) -> str:
        """循环执行（支持 parallel: true 并行加速）"""
        items_raw = step.get("items", [])
        items = resolve_ref(items_raw, self.context)
        loop_var = step.get("loop_var", "item")
        sub_steps = step.get("steps", [])
        collect_key = step.get("collect", "results")
        loop_condition = step.get("condition")  # loop 级别的条件过滤
        parallel = step.get("parallel", False)  # 并行执行

        _dict_mode = False
        _dict_items = {}
        if isinstance(items, dict):
            _dict_mode = True
            _dict_items = items
            items = list(items.keys())

        # ── 并行模式 ──
        # 注意：并行模式不支持 loop 级别 condition 过滤，每项独立线程执行子步骤
        if parallel and len(items) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import copy

            print(f"  🔄 并行循环开始，共 {len(items)} 项")

            def _run_one(idx, item):
                thread_ctx = copy.deepcopy(self.context)
                thread_ctx["context"][loop_var] = item
                if _dict_mode:
                    thread_ctx["context"][loop_var + "_value"] = _dict_items[item]

                thread_mify = copy.copy(self.mify)
                thread_mify.cookie = self.cookie

                tmp_engine = FlowEngine.__new__(FlowEngine)
                tmp_engine.config = self.config
                tmp_engine.inputs = self.inputs
                tmp_engine.mify = thread_mify
                tmp_engine.cookie = self.cookie
                tmp_engine.goto_count = {}
                tmp_engine.max_goto = 10
                tmp_engine.baseline_pr_no = None
                tmp_engine.baseline_pr_id = None
                tmp_engine.context = thread_ctx
                tmp_engine.steps_map = self.steps_map
                tmp_engine.terminals = self.terminals
                tmp_engine.state_file = None
                tmp_engine.progress_callback = None

                for sub_step in sub_steps:
                    tmp_engine.execute_step(sub_step)

                last_sub = sub_steps[-1]["id"]
                step_data = thread_ctx["steps"].get(last_sub, {})
                return step_data.get("extracted", step_data.get("result"))

            collected = [None] * len(items)
            with ThreadPoolExecutor(max_workers=min(len(items), 4)) as pool:
                future_map = {pool.submit(_run_one, i, item): i for i, item in enumerate(items)}
                for future in as_completed(future_map):
                    idx = future_map[future]
                    try:
                        collected[idx] = future.result()
                    except Exception as e:
                        print(f"  ❌ 并行项 {idx} 失败: {e}")
                        collected[idx] = {"_error": str(e)}

            # 合并结果到主 context
            if sub_steps:
                last_sub = sub_steps[-1]["id"]
                if not self.context["steps"].get(last_sub):
                    self.context["steps"][last_sub] = {"extracted": {}, "result": {}}
                merged_extracted = self.context["steps"][last_sub].get("extracted", {})
                for c in collected:
                    if isinstance(c, dict):
                        for k, v in c.items():
                            if k not in merged_extracted or not merged_extracted[k]:
                                merged_extracted[k] = v
                self.context["steps"][last_sub]["extracted"] = merged_extracted

            self.context["collected"][collect_key] = collected
            print(f"  ✅ 并行循环完成，收集 {len(collected)} 条结果")
            return step.get("goto")

        # ── 串行模式 ──
        collected = []
        print(f"  🔄 循环开始，共 {len(items)} 项")

        for i, item in enumerate(items):
            # dict 模式：loop_var = key, loop_var_value = value
            self.context["context"][loop_var] = item
            if _dict_mode:
                self.context["context"][loop_var + "_value"] = _dict_items[item]

            # 检查 loop 级别的 condition，跳过不满足的项
            if loop_condition:
                cond_result = self._eval_condition_expr(loop_condition)
                if not cond_result:
                    print(f"  ── 循环 {i+1}/{len(items)}: 条件不满足，跳过")
                    continue

            print(f"  ── 循环 {i+1}/{len(items)}")

            for sub_step in sub_steps:
                sub_result = self.execute_step(sub_step)
                # 循环内部不支持 goto，顺序执行

            # 收集最后一步的结果
            if sub_steps:
                last_sub = sub_steps[-1]["id"]
                step_data = self.context["steps"].get(last_sub, {})
                collected.append(step_data.get("extracted", step_data.get("result")))

        self.context["collected"][collect_key] = collected
        print(f"  ✅ 循环完成，收集 {len(collected)} 条结果")

        return step.get("goto")

    # ──────────────────────────────────────────────
    #  路由
    # ──────────────────────────────────────────────

    def _do_route(self, step: dict) -> str:
        """路由：根据条件选择执行子流程 YAML"""
        import yaml

        route_val = resolve_ref(step.get("switch_on", ""), self.context)
        routes = step.get("routes", {})

        # 匹配路由
        target_config = None
        for key, config_file in routes.items():
            if str(route_val) == str(key):
                target_config = config_file
                break

        if not target_config:
            target_config = step.get("default_config", "")

        if not target_config:
            print(f"  ❌ 路由未匹配: orderType={route_val}")
            return step.get("goto_fail")

        print(f"  🔀 路由: orderType={route_val} → {target_config}")

        # 读取子流程配置
        sub_config_path = Path(__file__).parent.parent / target_config
        if not sub_config_path.exists():
            print(f"  ❌ 配置文件不存在: {target_config}")
            return step.get("goto_fail")

        sub_config = yaml.safe_load(sub_config_path.read_text(encoding='utf-8'))

        # 用当前 inputs 执行子流程
        sub_engine = FlowEngine(sub_config, self.inputs, self.mify)

        # 复用 cookie
        sub_engine.cookie = self.cookie
        sub_engine.context["steps"] = self.context["steps"].copy()

        sub_engine.run()

        # 把子流程的步骤结果合并回来
        self.context["steps"].update(sub_engine.context["steps"])
        return None


# ──────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────

def _resolve_use_ref(ref: str, shared_steps: dict) -> Optional[dict]:
    """
    解析 use 引用，格式：common-steps.get_cookie
    返回共享步骤的深拷贝。
    """
    # 支持点分格式 common-steps.step_id
    if "." in ref:
        _, step_id = ref.split(".", 1)
    else:
        step_id = ref

    if step_id in shared_steps:
        import copy
        return copy.deepcopy(shared_steps[step_id])
    return None
