#!/usr/bin/env python3
"""卡片执行器 V3 - 每步完成发一张独立飞书卡片（直接调飞书API，用urllib）"""
import json, os, sys, time, urllib.request, urllib.error

# 加载 .env
_env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(_env_path):
    for line in open(_env_path):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip()

sys.path.insert(0, os.path.dirname(__file__))
from lib.client import MifyClient
from lib.flow import FlowEngine
from lib.config import load_config, load_mify_config
from lib.resolver import resolve_ref

# 飞书 Bot 配置
APP_ID = os.environ.get('FEISHU_APP_ID', 'cli_a9386acaa978dbc0')
APP_SECRET = os.environ.get('FEISHU_APP_SECRET', '')  # 必须从环境变量读取
OPEN_ID = os.environ.get('FEISHU_SENDER_OPEN_ID', 'ou_0f523a90cdfbb1cc84ccf67ba3fcf7ef')

if not APP_SECRET:
    print("❌ 错误: FEISHU_APP_SECRET 环境变量未设置", file=sys.stderr)
    print("请在 .env 文件中添加: FEISHU_APP_SECRET=your_app_secret", file=sys.stderr)
    sys.exit(1)

TOTAL_STEPS = 20

def api_call(url, data=None, method='POST'):
    """通用 API 调用"""
    req = urllib.request.Request(url, method=method)
    req.add_header('Content-Type', 'application/json')
    if data:
        req.data = json.dumps(data, ensure_ascii=False).encode('utf-8')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"⚠️ API 调用失败: {e}", file=sys.stderr)
        return {}

def get_tenant_token():
    """获取 tenant_access_token"""
    result = api_call('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
                       {'app_id': APP_ID, 'app_secret': APP_SECRET})
    return result.get('tenant_access_token', '')

TOKEN = get_tenant_token()

def send_card(title, content, color="blue"):
    """发送飞书互动卡片"""
    card = {
        "header": {
            "template": color,
            "title": {"tag": "plain_text", "content": title}
        },
        "elements": [
            {"tag": "markdown", "content": content}
        ]
    }
    payload = {
        "receive_id": OPEN_ID,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False)
    }
    url = 'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id'
    req = urllib.request.Request(url, method='POST')
    req.add_header('Authorization', f'Bearer {TOKEN}')
    req.add_header('Content-Type', 'application/json')
    req.data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('code') != 0:
                print(f"⚠️ 卡片发送失败: {result.get('msg')}", file=sys.stderr)
    except Exception as e:
        print(f"⚠️ 卡片发送异常: {e}", file=sys.stderr)

def _describe_step(step_id, action):
    """根据 action 类型返回人类可读的动作描述"""
    desc_map = {
        'http_call': 'HTTP 接口调用',
        'sql_query': 'SQL 查询',
        'sql_execute': 'SQL 写操作',
        'template': '模板渲染',
        'condition': '条件判断',
        'switch': '多路分支',
        'loop': '循环执行',
        'filter_collection': '集合过滤',
        'route': '子流程路由',
        'noop': '跳过',
    }
    return desc_map.get(action, action or '未知')

def _fmt_value(v, max_len=80):
    """格式化值，太长截断"""
    if v is None:
        return '(空)'
    s = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
    return s[:max_len] + ('...' if len(s) > max_len else '')

def _extract_step_detail(step_id, action, step_def, engine):
    """从引擎上下文提取每步的参数和结果"""
    ctx = engine.context
    step_data = ctx.get('steps', {}).get(step_id, {})
    extracted = step_data.get('extracted', {})
    result = step_data.get('result', {})

    # 参数描述
    param_lines = []
    params = step_def.get('params', {})
    if action == 'http_call':
        url = params.get('url', '')
        method = params.get('method', 'GET').upper()
        # 解析模板变量后的实际 URL
        from lib.resolver import resolve_ref
        try:
            real_url = resolve_ref(url, ctx) if '{{' in str(url) else url
        except Exception:
            real_url = url
        param_lines.append(f'{method} {_fmt_value(real_url, 100)}')
    elif action == 'sql_query':
        query = params.get('query', '')
        try:
            real_query = resolve_ref(query, ctx) if '{{' in str(query) else query
        except Exception:
            real_query = query
        param_lines.append(_fmt_value(real_query, 120))
    elif action == 'template':
        tpl = step_def.get('template', '')
        param_lines.append(f'模板: {tpl}')
    elif action == 'condition':
        param_lines.append(f'条件: {step_def.get("if", "")}')
    elif action == 'loop':
        items = step_def.get('items', '')
        param_lines.append(f'遍历: {_fmt_value(items, 60)}')
    elif action == 'filter_collection':
        param_lines.append(f'匹配字段: {step_def.get("match_field", "")}')

    # 结果描述
    result_lines = []
    if action in ('http_call', 'sql_query', 'sql_execute'):
        if extracted:
            for k, v in extracted.items():
                if k == 'cookie':
                    result_lines.append(f'{k}: (已获取, {len(str(v))}字符)')
                elif isinstance(v, list):
                    result_lines.append(f'{k}: [{len(v)}条记录]')
                elif isinstance(v, dict):
                    result_lines.append(f'{k}: {json.dumps(v, ensure_ascii=False)[:80]}')
                else:
                    result_lines.append(f'{k}: {_fmt_value(v, 80)}')
        if not result_lines and result:
            status = result.get('status_code', '')
            body = result.get('body', {})
            if status:
                result_lines.append(f'HTTP {status}')
            if isinstance(body, dict) and 'code' in body:
                result_lines.append(f'code={body["code"]}')
    elif action == 'template':
        output = step_data.get('output', '')
        result_lines.append(f'渲染完成, 长度 {len(output)}')
    elif action == 'condition':
        pass  # 条件跳转在卡片标题已体现

    return param_lines, result_lines

def send_step_card(seq, name, phase, status, elapsed=None, total=TOTAL_STEPS,
                    step_id=None, action=None, step_def=None, engine=None):
    """发送单步卡片 — 包含动作/参数/结果/耗时"""
    emoji = "✅" if status == "ok" else ("🔄" if status == "running" else "❌")
    color = "green" if status == "ok" else ("blue" if status == "running" else "red")

    title = f"{emoji} [{seq}/{total}] {name}"
    lines = [f'▸ **动作**: {_describe_step(step_id, action)}']

    # running 状态只显示动作
    if status == "running":
        send_card(title, "\n".join(lines), color)
        return

    # ok / error 状态显示参数+结果+耗时
    if step_def and engine and step_id:
        param_lines, result_lines = _extract_step_detail(step_id, action, step_def, engine)
        if param_lines:
            lines.append(f'▸ **参数**: {" ".join(param_lines)}')
        if result_lines:
            lines.append(f'▸ **结果**:')
            for rl in result_lines:
                lines.append(f'  {rl}')
    if elapsed is not None:
        lines.append(f'▸ **耗时**: {elapsed:.1f}s')

    send_card(title, "\n".join(lines), color)

def send_summary_card(params, results, cost):
    """发送汇总卡片"""
    lines = [
        f"📦 供应商: {params.get('supplierCode', '?')}",
        f"📦 物料: {list(params.get('materials', {}).values())}",
        "",
        "━━━ 执行结果 ━━━",
    ]
    for r in results:
        lines.append(f"{r['emoji']} [{r['seq']}/{TOTAL_STEPS}] {r['name']} — {r['detail']}")
    lines.append("")
    lines.append(f"⏱ 总耗时: {cost:.1f}s")
    
    send_card("🎯 造数工厂 · 执行完成", "\n".join(lines), "green")

# 解析参数
config = load_config(sys.argv[1])
params = {}
for arg in sys.argv[2:]:
    if '=' in arg:
        k, v = arg.split('=', 1)
        k = k.lstrip('-')
        if k.startswith('material'):
            params.setdefault('materials', {})[k] = v
        else:
            params[k] = json.loads(v) if v.startswith('{') or v.startswith('[') else v

inputs = {
    'stockOrg': params.get('stockOrg', 'MI_IOT'),
    'purchaseOrg': params.get('purchaseOrg', '2120'),
    'supplierCode': params.get('supplierCode', '108062'),
    'materials': params.get('materials', {}),
    'projectCode': params.get('projectCode', ''),
    'quantity1': int(params.get('quantity1', 10000)),
    'quantity2': int(params.get('quantity2', 10000)),
    'shipLocCode': params.get('shipLocCode', ''),
}

# 步骤定义
STEPS = [
    ("get_cookie", "获取Cookie", "准备阶段"),
    ("get_materials", "渲染物料模板", "准备阶段"),
    ("fetch_materials", "查询物料元数据", "准备阶段"),
    ("filter_materials", "过滤匹配物料", "准备阶段"),
    ("check_asl", "ASL供应商校验", "准备阶段"),
    ("build_pr", "拼PR请求体", "PR创建"),
    ("create_pr", "创建PR", "PR创建"),
    ("check_pr", "检查PR", "PR创建"),
    ("query_pr_info", "查询PR信息", "审批阶段"),
    ("approve_pr", "PR审批", "审批阶段"),
    ("query_items", "查询PR物料行", "PO创建"),
    ("query_contract", "查询合同", "PO创建"),
    ("build_prpo", "拼PR-PO请求体", "PO创建"),
    ("pr_to_po", "PR转PO", "PO创建"),
    ("check_po", "检查PO", "PO创建"),
    ("query_po_info", "查询PO信息", "ERP推送"),
    ("approve_po", "PO审批", "ERP推送"),
    ("query_erp", "查询ERP单号", "ERP推送"),
    ("check_erp", "检查ERP", "ERP推送"),
    ("repush_erp", "重新推送ERP", "ERP推送"),
]

# 初始化
mify_conf = load_mify_config()
mify = MifyClient(
    mify_conf['endpoint'], mify_conf['token'],
    'ou_0f523a90cdfbb1cc84ccf67ba3fcf7ef',
    mify_conf.get('sql_workflow_id', ''),
    mify_conf.get('sql_token', ''),
    mify_conf.get('workflow_id', '')
)

engine = FlowEngine(config, inputs, mify)

# 预取cookie
if not engine.cookie:
    cookie_url = resolve_ref('{{config.cookie_url}}', engine.context)
    if cookie_url:
        result = mify.http_call(cookie_url, 'GET')
        engine.cookie = result.get('body', {}).get('data', {}).get('result', {}).get('cookie', '')
        if engine.cookie:
            engine.context['steps']['get_cookie'] = {'extracted': {'cookie': engine.cookie}, 'output': engine.cookie}

# 发送启动卡片
send_card(
    "🏭 造数工厂 · 开始执行",
    f"📦 供应商: {inputs['supplierCode']}\n"
    f"📦 物料: {list(inputs['materials'].values())}\n"
    f"📦 数量: {inputs['quantity1']}/{inputs['quantity2']}\n\n"
    f"🚀 共 {TOTAL_STEPS} 步，逐步执行中...",
    "blue"
)

# 执行流程
steps = config.get('steps', [])
idx = 0
total_cost = 0.0
results = []

while idx < len(steps):
    step = steps[idx]
    sid = step.get('id', f's{idx}')
    
    step_info = next((s for s in STEPS if s[0] == sid), None)
    if not step_info:
        idx += 1
        continue
    
    step_id, step_name, phase = step_info
    seq = STEPS.index(step_info) + 1
    
    action = step.get('action')

    # 发送"执行中"卡片
    send_step_card(seq, step_name, phase, "running",
                    step_id=step_id, action=action, step_def=step, engine=engine)

    # 执行
    t0 = time.time()
    try:
        next_target = engine.execute_step(step)
        elapsed = time.time() - t0
        total_cost += elapsed
        status = "ok"
    except Exception as e:
        elapsed = time.time() - t0
        total_cost += elapsed
        status = "error"

    # 发送"完成"卡片（含参数/结果/耗时）
    send_step_card(seq, step_name, phase, status, elapsed,
                    step_id=step_id, action=action, step_def=step, engine=engine)
    # 汇总用 detail
    detail = f"{elapsed:.1f}s"
    results.append({"seq": seq, "name": step_name, "emoji": "✅" if status == "ok" else "❌", "detail": detail, "elapsed": elapsed})
    
    # 导航
    if next_target:
        found = False
        for i, s in enumerate(steps):
            if s.get('id') == next_target:
                idx = i
                found = True
                break
        if not found:
            break
    else:
        idx += 1

# 发送汇总卡片
send_summary_card(params, results, total_cost)
