#!/usr/bin/env python3
"""卡片执行器 - 每步输出 JSON，外部转发为飞书卡片"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
_env = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(_env):
    for line in open(_env):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip()

from lib.client import MifyClient
from lib.flow import FlowEngine
from lib.config import load_config, load_mify_config
from lib.resolver import resolve_ref

def emit(obj): print(json.dumps(obj, ensure_ascii=False), flush=True)

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

mify_conf = load_mify_config()
mify = MifyClient(mify_conf['endpoint'], mify_conf['token'],
    'ou_0f523a90cdfbb1cc84ccf67ba3fcf7ef',
    mify_conf.get('sql_workflow_id',''), mify_conf.get('sql_token',''), mify_conf.get('workflow_id',''))
engine = FlowEngine(config, inputs, mify)

if not engine.cookie:
    cu = resolve_ref('{{config.cookie_url}}', engine.context)
    if cu:
        r = mify.http_call(cu, 'GET')
        engine.cookie = r.get('body',{}).get('data',{}).get('result',{}).get('cookie','')
        if engine.cookie:
            engine.context['steps']['get_cookie'] = {'extracted':{'cookie':engine.cookie},'output':engine.cookie}

NAMES = {
    'get_cookie':'获取Cookie','get_materials':'渲染物料模板','fetch_materials':'查询物料元数据',
    'filter_materials':'过滤匹配物料','check_asl':'ASL供应商校验','build_pr':'拼PR请求体',
    'create_pr':'创建PR','check_pr':'检查PR','query_pr_info':'查询PR信息',
    'approve_pr':'PR审批','query_items':'查询PR物料行','query_contract':'查询合同',
    'build_prpo':'拼PR-PO请求体','pr_to_po':'PR转PO','check_po':'检查PO',
    'query_po_info':'查询PO信息','approve_po':'PO审批','query_erp':'查询ERP单号',
    'check_erp':'检查ERP','repush_erp':'重新推送ERP',
}
PHASE = {
    'get_cookie':('准备阶段',1),'get_materials':('准备阶段',2),'fetch_materials':('准备阶段',3),
    'filter_materials':('准备阶段',4),'check_asl':('准备阶段',5),
    'build_pr':('PR创建',6),'create_pr':('PR创建',7),'check_pr':('PR创建',8),
    'query_pr_info':('审批阶段',9),'approve_pr':('审批阶段',10),
    'query_items':('PO创建',11),'query_contract':('PO创建',12),'build_prpo':('PO创建',13),
    'pr_to_po':('PO创建',14),'check_po':('PO创建',15),
    'query_po_info':('ERP推送',16),'approve_po':('ERP推送',17),
    'query_erp':('ERP推送',18),'check_erp':('ERP推送',19),'repush_erp':('ERP推送',20),
}

steps = config.get('steps', [])
idx = 0; total = 0.0; last_phase = ''

while idx < len(steps):
    step = steps[idx]
    sid = step.get('id', f's{idx}')
    action = step.get('action','?')
    phase, seq = PHASE.get(sid, ('其他',99))
    name = NAMES.get(sid, sid)
    t0 = time.time()
    try:
        next_target = engine.execute_step(step)
        elapsed = time.time() - t0; total += elapsed
        ext = engine.context.get('steps',{}).get(sid,{}).get('extracted',{})
        data = {k: str(v)[:80] for k,v in (ext or {}).items() if v not in (None,'',[],{})}
        status = 'ok'; error = None
    except Exception as e:
        elapsed = time.time() - t0; total += elapsed
        data = {}; status = 'error'; error = str(e)[:100]

    emit({'step':sid,'seq':seq,'name':name,'phase':phase,
          'changed':(phase!=last_phase),'status':status,
          't':round(elapsed,1),'data':data,'error':error,'cost':round(total,1)})
    last_phase = phase

    if next_target:
        found = False
        for i,s in enumerate(steps):
            if s.get('id')==next_target: idx=i; found=True; break
        if not found: emit({'terminal':next_target,'cost':round(total,1)}); break
    else: idx += 1

emit({'done':True,'cost':round(total,1)})
