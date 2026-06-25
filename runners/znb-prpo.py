#!/usr/bin/env python3
"""ZNB-PRPO 造单流程 - 通过 mify 带Cookie调用"""

import json
import time
import subprocess
import sys

MIFY_URL = "https://service.mify.mioffice.cn/api/v1/workflows/run"
MIFY_TOKEN = "app-lgZyqi1INjxp7o05Ym76jKbw"
USER = "liusixing"

CONFIG = {
    "db_uri": "mysql+pymysql://isc_scm_test_wn:vKoc3jfIM2v4z4pPwruR6YaUpCOaHZep@ksc.test.mysql01.b2c.srv:3304/isc_scm_test",
    "cookie_url": "https://toolskit.test.mi.com/datacube/getSCMCookie",
    "scm_base": "https://scm.test.mioffice.cn",
    "bpm_base": "https://bpm-infra.test.mioffice.cn/bpmtool/api/bpmThree/approve",
}

INPUTS = {
    "stockOrg": "MI_IOT",
    "purchaseOrg": "2120",
    "supplierCode": "108062",
    "materials": {"materialCode1": "1710301000006B"},
    "projectCode": "EcoOdmJdm20240708220947-EU",
    "shipLocCode": "129797",
}

COOKIE = ""


def mify_call(url, method="get", body="", cookie="", timeout=60):
    """通过 mify 工作流调用 HTTP"""
    payload = {
        "inputs": {"url": url, "method": method, "body": body, "cookie": cookie},
        "user": USER,
        "response_mode": "streaming",
    }
    
    cmd = [
        "curl", "-s", "-X", "POST", MIFY_URL,
        "-H", f"Authorization: Bearer {MIFY_TOKEN}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps(payload),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    output = result.stdout
    
    for line in output.strip().split("\n"):
        if line.startswith("data: "):
            try:
                event = json.loads(line[6:])
                if event["event"] == "workflow_finished":
                    outputs = event["data"]["outputs"]
                    body_str = outputs.get("body", "{}")
                    status = outputs.get("status_code", 0)
                    try:
                        parsed_body = json.loads(body_str)
                    except json.JSONDecodeError:
                        parsed_body = {"_raw": body_str[:500]}
                    return {"status_code": status, "body": parsed_body}
            except (json.JSONDecodeError, KeyError):
                continue
    
    return None


def log(msg):
    print(msg, flush=True)


def step1_get_cookie():
    """① 获取 SCM Cookie"""
    log("\n📌 ① 获取Cookie...")
    resp = mify_call(CONFIG["cookie_url"], "get")
    if not resp:
        log("  ❌ Cookie获取失败（调用无返回）")
        return None
    
    cookie = resp["body"].get("data", {}).get("result", {}).get("cookie", "")
    if not cookie:
        log(f"  ❌ Cookie为空: {resp['body']}")
        return None
    
    log(f"  ✅ Cookie获取成功 (长度: {len(cookie)})")
    return cookie


def step2_check_asl(cookie):
    """② ASL前置校验"""
    log("\n📌 ② ASL前置校验...")
    
    for mat_key, mat_code in INPUTS["materials"].items():
        body = json.dumps({
            "moduleCode": "Purchase9",
            "batch": [{"stockOrg": INPUTS["stockOrg"], "xmCode": mat_code}],
        })
        resp = mify_call(
            f"{CONFIG['scm_base']}/mrp/purchase/material-supplier-relations/batch",
            "post", body, cookie
        )
        
        if not resp:
            log(f"  ❌ {mat_code} 调用失败")
            return False
        
        code = resp["body"].get("code", "")
        if str(code) == "0":
            data = resp["body"].get("data", [])
            suppliers = [d.get("label", "") for d in data[:3]]
            log(f"  ✅ {mat_code} ASL校验通过, 匹配供应商: {', '.join(suppliers)}")
        else:
            msg = resp["body"].get("message", "未知错误")
            log(f"  ❌ {mat_code} ASL校验失败: {msg}")
            return False
    
    return True


def step3_build_pr():
    """③ 拼PR请求体"""
    log("\n📌 ③ 拼PR请求体...")
    
    materials_list = []
    for i, (mat_key, mat_code) in enumerate(INPUTS["materials"].items(), 1):
        materials_list.append({
            "key": i,
            "description": "电视结构件_LCM组件_结构组件_背板组件_TVODMHJ01_ADFE20240422_ZNGC",
            "pnCode": "1690201000003",
            "purchaseOrg": INPUTS["purchaseOrg"],
            "applicationNum": 100000,
            "catePathName": "电视结构件.LCM组件.结构组件",
            "baseUom": "PC",
            "minPackingQuantity": "10",
            "minOrderQuantity": "10",
            "xmCode": mat_code,
            "number": 10000,
            "supplierCode": INPUTS["supplierCode"],
            "receiveDate": 1798736461000,
            "isNew": 1,
            "materialCode": mat_code,
            "materialDesc": "电视结构件_LCM组件_结构组件_背板组件_TVODMHJ01_ADFE20240422_ZNGC",
            "manufacturer": "ZNGC",
            "spCode": "ADFE20240422",
            "brand": "TEST_Ⅱ",
            "label": "1690201000003A(电视结构件_LCM组件_结构组件_背板组件_TVODMHJ01_ADFE20240422_ZNGC)",
            "value": mat_code,
            "catePathCode": "169.02.01",
            "codeDescEn": "TV-ME_LCM-Assy_ME-Assy_背板组件_TVODMHJ01_ADFE20240422_ZNGC",
            "materialGroupCode": "R4016902",
            "materialGroup": "电视结构件-LCM组件",
            "mgroup": {"code": "R4016902", "name": "电视结构件-LCM组件"},
            "cvpnCode": "1690201000003",
            "supplierCodeOption": {"label": "100774-纬创资通（中山）有限公司", "value": "100774", "key": "100774"},
            "isStructure": True,
            "receiveDateTimeStamp": 1717430400000,
            "rowNo": "",
            "remarks": "",
        })
    
    pr_body = {
        "stockOrg": INPUTS["stockOrg"],
        "materials": materials_list,
        "purchaseReason": "14",
        "receiveFactoryId": "",
        "projectCode": INPUTS["projectCode"],
        "materialCheckerList": ["kangtao"],
        "isSubmit": True,
        "purchaseType": 9,
    }
    
    log(f"  ✅ PR请求体已生成 ({len(materials_list)} 个物料)")
    return pr_body


def step4_create_pr(cookie, pr_body):
    """④ 创建PR"""
    log("\n📌 ④ 创建PR...")
    
    resp = mify_call(
        f"{CONFIG['scm_base']}/mrp/pr/ordinary",
        "post", json.dumps(pr_body), cookie
    )
    
    if not resp:
        log("  ❌ PR创建调用失败")
        return None
    
    code = resp["body"].get("code", "")
    msg = resp["body"].get("message", "")
    
    if str(code) != "0":
        log(f"  ❌ PR创建失败: {msg}")
        return None
    
    log(f"  ✅ PR创建成功")
    return resp


def main():
    print("=" * 60)
    print("🚀 ZNB-PRPO 造单流程")
    print("=" * 60)
    
    # ① 获取Cookie
    cookie = step1_get_cookie()
    if not cookie:
        return
    
    # ② ASL校验
    if not step2_check_asl(cookie):
        return
    
    # ③ 拼PR请求体
    pr_body = step3_build_pr()
    
    # ④ 创建PR
    pr_resp = step4_create_pr(cookie, pr_body)
    if not pr_resp:
        return
    
    print("\n" + "=" * 60)
    print("✅ 前4步完成：Cookie → ASL校验 → 拼PR → 创建PR")
    print("⏳ 后续步骤（SQL查询、审批、合同、PO）需要 mify sql_query 工具")
    print("=" * 60)


if __name__ == "__main__":
    main()
