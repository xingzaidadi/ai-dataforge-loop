#!/usr/bin/env python3
"""分步执行器 — 每步输出一行 JSON 状态，供外部实时转发"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(__file__))

# 加载 .env 并注入 os.environ
_env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(_env_path):
    for line in open(_env_path):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip()

from lib.client import MifyClient
from lib.flow import FlowEngine
from lib.config import load_config, load_mify_config

def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)

config = load_config(sys.argv[1])
mify_conf = load_mify_config()
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

mify = MifyClient(
    mify_conf.get('endpoint', ''),
    mify_conf.get('token', ''),
    'ou_0f523a90cdfbb1cc84ccf67ba3fcf7ef',
    mify_conf.get('sql_workflow_id', ''),
    mify_conf.get('sql_token', ''),
    mify_conf.get('workflow_id', ''),
)

engine = FlowEngine(config, inputs, mify)
# 预取 cookie（与 engine.py 一致）
if not engine.cookie:
    from lib.resolver import resolve_ref
    cookie_url = resolve_ref('{{config.cookie_url}}', engine.context)
    if cookie_url:
        result = mify.http_call(cookie_url, 'GET')
        engine.cookie = result.get('body', {}).get('data', {}).get('result', {}).get('cookie', '')
        if engine.cookie:
            engine.context['steps']['get_cookie'] = {'extracted': {'cookie': engine.cookie}, 'output': engine.cookie}

steps = config.get('steps', [])
idx = 0

while idx < len(steps):
    step = steps[idx]
    sid = step.get('id', f's{idx}')
    action = step.get('action', '?')
    t0 = time.time()
    try:
        next_target = engine.execute_step(step)
        elapsed = time.time() - t0
        ext = engine.context.get('steps', {}).get(sid, {}).get('extracted', {})
        # 精简结果
        summary = {}
        for k, v in (ext or {}).items():
            if v is not None and v != '' and v != []:
                summary[k] = str(v)[:80]
        emit({'step': sid, 'action': action, 'status': 'ok', 't': f'{elapsed:.1f}s', 'data': summary})
    except Exception as e:
        elapsed = time.time() - t0
        emit({'step': sid, 'action': action, 'status': 'error', 't': f'{elapsed:.1f}s', 'error': str(e)[:100]})

    if next_target:
        found = False
        for i, s in enumerate(steps):
            if s.get('id') == next_target:
                idx = i; found = True; break
        if not found:
            emit({'terminal': next_target})
            break
    else:
        idx += 1

emit({'done': True})
