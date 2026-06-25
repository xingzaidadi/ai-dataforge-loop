# AI 数据智造引擎 — 极简设计方案 v2

## 一、核心架构

```
用户 → Skill（编排引擎，读配置，拼参数，做判断）
    → mify（只有两个工具：http_call / sql_query）
    → Skill 解析返回，决定下一步
    → 反复调 mify，直到流程走完
```

**mify 的定位**：两个工具，零业务逻辑。

---

## 二、mify 工具定义

### 工具1：http_call

调用任意 HTTP 接口。

**入参：**
```json
{
  "url": "https://xxx.com/api/path",
  "method": "POST",
  "headers": {
    "Cookie": "xxx",
    "Content-Type": "application/json"
  },
  "body": { ... },
  "timeout": 30
}
```

**出参：**
```json
{
  "status_code": 200,
  "headers": { ... },
  "body": { "code": "0", "data": { ... } }
}
```

### 工具2：sql_query

执行 SQL 查询。

**入参：**
```json
{
  "db_uri": "${SCM_DB_URI}",
  "query": "SELECT purchase_no, business_key FROM m_purchase WHERE ...",
  "format": "json"
}
```

**出参：**
```json
{
  "rows": [
    {"purchase_no": "8440015387", "business_key": "xxx"}
  ]
}
```

---

## 三、Skill 编排逻辑

Skill 的工作流程：

1. **读配置** → 根据用户意图选择对应的流程配置文件
2. **执行步骤** → 按配置文件的 steps 顺序，一步步执行
3. **每步操作**：
   - 从上下文取变量（用户输入、前序步骤的结果）
   - 如果是 template 类型 → 用 Jinja2 模板拼装参数
   - 如果是 http 类型 → 调 mify 的 http_call
   - 如果是 sql 类型 → 调 mify 的 sql_query
   - 从返回结果中提取需要的字段，存入上下文
4. **条件判断** → 根据返回值决定走哪个分支
5. **循环** → 对列表中的每个元素重复调用 mify
6. **返回结果** → 流程结束，给用户最终结果

### 变量引用语法

```
{{inputs.xxx}}          → 用户输入的参数
{{steps.step_id.xxx}}   → 某步骤的返回值（用 JSONPath 提取）
{{config.xxx}}          → 全局配置
{{context.xxx}}         → 当前上下文临时变量
```

---

## 四、流程配置格式

### 4.1 完整示例：ZNB-PRPO 造单

```yaml
# configs/znb-prpo.yaml
name: ZNB普通物料PRPO造单
description: 输入物料 → 创建PR → PR审批 → 查合同 → PR转PO → PO审批 → 查ERP单号

# 用户输入
inputs:
  stockOrg:       { label: 库存组织, required: true }
  purchaseOrg:    { label: 采购组织, required: true }
  supplierCode:   { label: 供应商编码, required: true }
  materials:      { label: 物料列表, required: true, type: object }
  projectCode:    { label: 项目编码, required: false }
  shipLocCode:    { label: 发货地点, required: true }

# 全局配置
config:
  db_uri: "${SCM_DB_URI}"
  cookie_url: "${SCM_COOKIE_URL}"
  scm_base: "${SCM_BASE_URL}"
  bpm_base: "${BPM_APPROVE_URL}"

# 流程步骤
steps:
  # ── 第1步：获取Cookie ──
  - id: get_cookie
    action: http_call
    params:
      url: "{{config.cookie_url}}"
      method: GET
    extract:
      cookie: "$.body.data.result.cookie"
    on_error:
      message: "cookie获取失败，尝试联系管理员"

  # ── 第2步：ASL前置校验（遍历每个物料）──
  - id: check_asl
    action: loop
    items: "{{inputs.materials}}"        # 遍历 materials 字典
    loop_var: material_key               # 当前遍历的key，如 materialCode1
    steps:
      - id: check_one_asl
        action: http_call
        params:
          url: "{{config.scm_base}}/mrp/purchase/material-supplier-relations/batch"
          method: POST
          headers:
            Cookie: "{{steps.get_cookie.extracted.cookie}}"
          body:
            moduleCode: "Purchase9"
            batch:
              - stockOrg: "{{inputs.stockOrg}}"
                xmCode: "{{inputs.materials[context.material_key]}}"
        extract:
          code: "$.body.code"
          message: "$.body.message"
        on_error:
          message: "ASL检查失败: {{steps.check_one_asl.extracted.message}}"
    after_loop:
      check: "所有 code == '0'"
      on_fail: "收集所有非0的message，拼接返回错误"

  # ── 第3步：拼PR请求体（模板，不调mify）──
  - id: build_pr
    action: template
    template: "templates/pr-body.json.j2"
    context:
      stockOrg: "{{inputs.stockOrg}}"
      purchaseOrg: "{{inputs.purchaseOrg}}"
      supplierCode: "{{inputs.supplierCode}}"
      projectCode: "{{inputs.projectCode}}"
      materials: "{{inputs.materials}}"

  # ── 第4步：创建PR ──
  - id: create_pr
    action: http_call
    params:
      url: "{{config.scm_base}}/mrp/pr/ordinary"
      method: POST
      headers:
        Cookie: "{{steps.get_cookie.extracted.cookie}}"
      body: "{{steps.build_pr.output}}"
    extract:
      code: "$.body.code"
      message: "$.body.message"

  # ── 第5步：检查PR结果 ──
  - id: check_pr
    action: condition
    if: "{{steps.create_pr.extracted.code}} == '0'"
    then: query_pr_info
    else: END_PR_FAIL

  # ── 第6步：查business_key ──
  - id: query_pr_info
    action: sql_query
    params:
      db_uri: "{{config.db_uri}}"
      query: |
        SELECT mp.purchase_no, mp.business_key
        FROM m_purchase mp
        INNER JOIN m_purchase_item mpi ON mp.purchase_no = mpi.purchase_no
        WHERE mpi.xm_code IN (...)
          AND mp.stock_org = '{{inputs.stockOrg}}'
          AND mpi.supplier_code = '{{inputs.supplierCode}}'
          AND mp.status = 10
        ORDER BY mp.updated_at DESC
        LIMIT 1
    extract:
      purchase_no: "$.rows[0].purchase_no"
      business_key: "$.rows[0].business_key"

  # ── 第7步：PR审批 ──
  - id: approve_pr
    action: http_call
    params:
      url: "{{config.bpm_base}}?businessKey={{steps.query_pr_info.extracted.business_key}}"
      method: GET
    retry: {max: 10, interval_ms: 445}
    extract:
      code: "$.body.code"

  # ── 第8步：查PR物料行 ──
  - id: query_items
    action: sql_query
    params:
      db_uri: "{{config.db_uri}}"
      query: |
        SELECT id, xm_code FROM m_purchase_item
        WHERE purchase_no = '{{steps.query_pr_info.extracted.purchase_no}}'
    extract:
      items: "$.rows"

  # ── 第9步：按采购组织分派 ──
  - id: route_contract
    action: switch
    switch_on: "{{inputs.purchaseOrg}}"
    cases:
      - match: "1110"
        goto: query_contract_phone
      - match: ["1131", "1132", "1133", "1134"]
        goto: query_contract_non_phone
    default: query_contract_non_phone

  # ── 第9a步：查合同号（手机，遍历物料）──
  - id: query_contract_phone
    action: loop
    items: "{{steps.query_items.extracted.items}}"
    loop_var: item
    steps:
      - id: query_one_contract
        action: sql_query
        params:
          db_uri: "{{config.db_uri}}"
          query: |
            SELECT gfa_no, gfa_row_no, material_code
            FROM m_purchase_srm_gfa
            WHERE gfa_enable=1
              AND sp_code={{inputs.supplierCode}}
              AND material_code='{{context.item.xm_code}}'
              AND purchase_org='{{inputs.purchaseOrg}}'
              AND UNIX_TIMESTAMP(CURRENT_TIMESTAMP) * 1000 < price_end_date
              AND price_type = 'ZNB'
            ORDER BY contract_date DESC
            LIMIT 1
        extract:
          gfa_no: "$.rows[0].gfa_no"
          gfa_row_no: "$.rows[0].gfa_row_no"
    collect: contracts    # 收集每次循环的结果为列表
    goto: build_prpo

  # ── 第9b步：查合同号（非手机，遍历物料）──
  - id: query_contract_non_phone
    action: loop
    items: "{{steps.query_items.extracted.items}}"
    loop_var: item
    steps:
      - id: query_one_contract_nm
        action: sql_query
        params:
          db_uri: "{{config.db_uri}}"
          query: |
            SELECT gfa_no, gfa_row_no, material_code
            FROM m_purchase_srm_gfa
            WHERE gfa_enable=1
              AND sp_code={{inputs.supplierCode}}
              AND material_code='{{context.item.xm_code}}'
              AND purchase_org='{{inputs.purchaseOrg}}'
              AND UNIX_TIMESTAMP(CURRENT_TIMESTAMP) * 1000 < price_end_date
            ORDER BY contract_date DESC
            LIMIT 1
        extract:
          gfa_no: "$.rows[0].gfa_no"
          gfa_row_no: "$.rows[0].gfa_row_no"
    collect: contracts
    goto: build_prpo

  # ── 第10步：拼PR转PO入参 ──
  - id: build_prpo
    action: template
    template: "templates/prpo-params.json.j2"
    context:
      contracts: "{{steps[latest_contracts].collected.contracts}}"
      pr_items: "{{steps.query_items.extracted.items}}"
      purchaseNo: "{{steps.query_pr_info.extracted.purchase_no}}"
      stockOrg: "{{inputs.stockOrg}}"
      supplierCode: "{{inputs.supplierCode}}"
      purchaseOrg: "{{inputs.purchaseOrg}}"

  # ── 第11步：PR转PO ──
  - id: pr_to_po
    action: http_call
    params:
      url: "{{config.scm_base}}/mrp/purchase/prpo/generatePo"
      method: POST
      headers:
        Cookie: "{{steps.get_cookie.extracted.cookie}}"
      body: "{{steps.build_prpo.output}}"
    extract:
      code: "$.body.code"
      message: "$.body.message"

  # ── 第12步：检查PO结果 ──
  - id: check_po
    action: condition
    if: "{{steps.pr_to_po.extracted.code}} == '0'"
    then: query_po_info
    else: END_PO_FAIL

  # ── 第13步：查PO信息 ──
  - id: query_po_info
    action: sql_query
    params:
      db_uri: "{{config.db_uri}}"
      query: |
        SELECT DISTINCT po.business_key, po.purchase_order_no
        FROM m_purchase_order po
        INNER JOIN m_purchase_order_item poi ON po.id = poi.purchase_order_id
        WHERE poi.source_no = '{{steps.query_pr_info.extracted.purchase_no}}'
    extract:
      po_business_key: "$.rows[0].business_key"
      purchase_order_no: "$.rows[0].purchase_order_no"

  # ── 第14步：PO审批 ──
  - id: approve_po
    action: http_call
    params:
      url: "{{config.bpm_base}}?businessKey={{steps.query_po_info.extracted.po_business_key}}"
      method: GET
    retry: {max: 3, interval_ms: 100}
    extract:
      code: "$.body.code"

  # ── 第15步：等5秒查ERP单号 ──
  - id: query_erp
    action: sql_query
    wait: 5
    params:
      db_uri: "{{config.db_uri}}"
      query: |
        SELECT DISTINCT po.erp_purchase_order_no
        FROM m_purchase_order po
        INNER JOIN m_purchase_order_item poi ON po.id = poi.purchase_order_id
        WHERE poi.source_no = '{{steps.query_pr_info.extracted.purchase_no}}'
    extract:
      erp_no: "$.rows[0].erp_purchase_order_no"

  # ── 第16步：判断ERP单号 ──
  - id: check_erp
    action: condition
    if: "{{steps.query_erp.extracted.erp_no}} != ''"
    then: SUCCESS
    else: repush_erp

  # ── 第17步：重新推送 ──
  - id: repush_erp
    action: http_call
    params:
      url: "{{config.scm_base}}/mrp/purchase/prpo/repushPo"
      method: POST
      headers:
        Cookie: "{{steps.get_cookie.extracted.cookie}}"
      body:
        purchaseOrderNo: "{{steps.query_po_info.extracted.purchase_order_no}}"
        purchaseNo: "{{steps.query_pr_info.extracted.purchase_no}}"
    extract:
      erp_no: "$.body.erp_purchase_order_no"
    goto: check_erp

# ── 终止节点 ──
terminals:
  SUCCESS:
    type: success
    message: |
      🎉 造单成功！
      PR号: {{steps.query_pr_info.extracted.purchase_no}}
      PO号: {{steps.query_po_info.extracted.purchase_order_no}}
      ERP单号: {{steps.query_erp.extracted.erp_no}}

  END_PR_FAIL:
    type: error
    message: "PR创建失败: {{steps.create_pr.extracted.message}}"

  END_PO_FAIL:
    type: error
    message: "PO创建失败: {{steps.pr_to_po.extracted.message}}"
```

---

## 五、步骤类型（action）汇总

引擎 action 分为核心 6 种和扩展能力：

| action | 类型 | 说明 | 调mify? | 示例 |
|--------|------|------|---------|------|
| `http_call` | 核心 | 调一次HTTP接口 | ✅ http_call | 获取cookie、创建PR、审批 |
| `sql_query` | 核心 | 执行一次SQL查询 | ✅ sql_query | 查business_key、查合同 |
| `template` | 核心 | Jinja2模板拼接 | ❌ 纯本地 | 拼PR请求体、拼PO入参 |
| `condition` | 核心 | 条件分支 | ❌ 纯本地 | 判断code是否为0 |
| `switch` | 核心 | 多路分支 | ❌ 纯本地 | 按采购组织走不同合同查询 |
| `loop` | 核心 | 循环（内部含多个步骤） | ✅ 内部循环调mify | 遍历物料查ASL、遍历查合同 |
| `route` | 扩展 | 路由到子流程配置 | ❌ 纯本地 | 按订单类型分发 |
| `sql_execute` | 扩展 | 执行 SQL 写操作 | ✅ sql_query/直连 | 配额修正 |
| `filter_collection` | 扩展 | 过滤集合结果 | ❌ 纯本地 | 过滤物料查询结果 |

**核心 6 种 action 负责表达主要流程，扩展 action 用于路由、数据修正和集合过滤。**

---

## 六、与之前方案对比

| 维度 | v1（mify有batch能力） | v2（极简版） |
|------|---------------------|-------------|
| mify能力 | http_call + sql_query + http_batch + bpm_approve | **只有 http_call + sql_query** |
| 批量操作 | mify内置batch | Skill循环调mify |
| 审批 | mify有专门bpm工具 | Skill调http_call（传审批URL） |
| 复杂度 | mify中等 | **mify极简** |
| 灵活性 | 中 | **最高**（Skill完全控制每一步） |

---

## 七、落地路径

### Phase 1：mify 实现两个工具
- http_call：通用HTTP客户端（支持GET/POST/PUT/DELETE，带超时）
- sql_query：通用SQL执行（传连接串+SQL，返回JSON）

### Phase 2：Skill 编排引擎
- 配置文件解析（YAML）
- 变量引用解析（{{steps.xxx}}）
- Jinja2 模板渲染
- 条件判断 + 循环执行
- 错误处理 + 重试

### Phase 3：验证
- 用 ZNB-PRPO 配置跑通全流程
- 对比 Dify 原流程结果

### Phase 4：扩展
- 新造单场景 → 写新yaml + 模板
- 不改任何代码
