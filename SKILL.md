---
name: mify-data-factory
display_name: 数枢(DataPivot)
version: 3.2.0
description: |
  Mify 造数工厂：面向供应链测试场景的智能数据构造与流程编排 Skill。
  触发场景：用户说"帮我造单""造一条采购订单""PRPO拉料""帮我造数""造一条测试数据""ZNB造单""ZWW造单"等造数相关请求。
  不触发场景：查询已有订单状态、报销、审批、查物料信息、问接口文档。
author: MI
track: C-跨部门协同
platform: 工作虾(Open Claw)
spec: MIT AI Skill 撰写规范 V1.1-beta
tags: [造数, 测试数据, 供应链, 流程编排, Agent, 跨系统, PRPO]
---

# 数枢(DataPivot) · AI 数据智造引擎

> 从一句业务诉求，到一条可验证的供应链数据链路。

## 1. 问题描述

在复杂供应链业务里，一条可用的测试数据要跨 **7+ 系统、40+ 步操作**，涉及采购、审批、ERP、QA、DBA 多方协同。这套协同知识通常只存在于少数熟手脑中，人一走经验就断。

传统做法的困境：
- **手工造数**：单场景 1-3 人天，严重依赖个人经验
- **脚本自动化**：每个场景独立一套脚本，复制粘贴改参数，维护成本随场景数指数增长
- **低代码平台**：节点越加越多，分支越连越乱，变成谁也不敢动的"节点巨图"

数枢把这条"长在人脑里"的协同链路，沉淀为**机器可执行、团队可复用、新人可接手**的能力。

## 2. 触发场景

**触发**——当用户表达以下意图时调用：
- "帮我造一条 XX 采购订单"
- "ZNB 造单""ZWW 造单""PRPO 拉料"
- "造一批测试数据""准备一条全链路测试数据"
- "生态链的标准采购订单造一条"
- 任何"构造一条需要跨多个系统、带状态流转的业务测试数据"的诉求

**不触发**——以下场景明确不归本 Skill 管：
- 只读查询（"查下这条订单状态"）
- 纯接口调试（"帮我调下这个接口"）
- 报销、审批等与造数无关的对话
- 查物料信息、问接口文档

## 3. 交互契约（三道闸）

以下规则必须严格遵守，违反任意一条即为 Skill 执行失败：

### 闸 1：必填校验

参数不完整时禁止执行。缺少以下任意一项，必须追问补齐，不得自行猜测或填充默认值：
- 订单类型（ZNB/ZWW/ZDO 等）
- 采购组织
- 供应商编码
- 物料信息（物料编码 + 数量）

### 闸 2：条件必填

不同订单类型动态追加必填项：
- 寄售 → 需供应商库存地
- 跨公司 → 需收发公司编码
- 委外 → 需工序路线

缺则继续追问，不执行。

### 闸 3：执行前确认

参数齐备后，必须生成参数确认卡片，逐项列出最终参数。用户明确回复"确认"后才真正执行。用户拒绝或沉默时，必须中止执行并告知"已取消"。

### 业务映射（自然语言 → 系统字段）

Agent 负责把口语化业务词映射为系统字段（见下方采购组织映射表）。禁止让用户自己查编码。

### 脱敏输出

日志和输出中禁止暴露数据库密码、API Token 等凭证信息。执行结果只展示业务数据（单号、状态、关键字段），不展示原始 HTTP 响应体全文。

## 4. 五层架构

```
┌─────────────────────────────────────────────────┐
│  AI Agent 对话层 — 参数收集 / 确认 / 业务映射      │  ← 降低使用门槛
├─────────────────────────────────────────────────┤
│  Python 编排引擎 — 条件 / 循环 / 路由 / 重试 / 状态 │  ← 流程可测试、可版本化
├─────────────────────────────────────────────────┤
│  YAML 配置层 — 声明式描述业务流程差异              │  ← 新增场景只改配置
├─────────────────────────────────────────────────┤
│  Jinja2 模板层 — 复杂请求体结构化治理             │  ← 请求结构可审查
├─────────────────────────────────────────────────┤
│  执行层（HTTP + SQL）— 薄执行通道                │  ← 稳定、简单、易替换
└─────────────────────────────────────────────────┘
```

| 层 | 文件 | 职责 |
|---|------|------|
| **对话层** | `prompt.md` | 收集参数、确认、映射转换、格式化输出 |
| **编排引擎** | `engine.py` | 读 YAML、执行 9 种 Action、管理状态/重试/分支 |
| **YAML 配置层** | `configs/*.yaml` | 声明式描述每种订单的完整流程步骤 |
| **模板层** | `templates/*.j2` | Jinja2 渲染复杂请求体 |
| **执行层** | mify 平台 | 只提供 `http_call` 和 `sql_query` 两个通用工具 |

## 5. 流程 DSL：9 种 Action

| Action | 作用 | 调执行层 |
|--------|------|---------|
| `http_call` | 通过 mify 调 HTTP 接口 | 是 |
| `sql_query` | 查询数据库状态 | 是 |
| `sql_execute` | 数据修正（配额/状态补齐），写操作须经确认闸 | 是 |
| `template` | 渲染 Jinja2 模板为请求体 | 否 |
| `condition` | 条件分支（if/then/else） | 否 |
| `switch` | 多路分支（switch_on/cases） | 否 |
| `loop` | 循环遍历（items/collect） | 间接 |
| `route` | 路由到子流程（orderType/routes） | 否 |
| `filter_collection` | 集合过滤（source/match_field） | 否 |

新增一种业务场景 = 新增 `configs/xxx.yaml` + 新增 Jinja2 模板 + 在 prompt 补映射，**不改任何 Python 代码**。

## 6. 目录结构

```
mify-data-factory/
├── SKILL.md                  # 本文件（Skill 声明）
├── prompt.md                 # 对话层提示词（参数收集/确认/映射）
├── design.md                 # 详细设计方案
├── engine.py                 # 通用编排引擎（9 种 Action 实现）
├── lib/                      # 引擎核心模块
│   ├── client.py             # HTTP/SSE 客户端
│   ├── config.py             # 配置加载
│   ├── flow.py               # 流程控制
│   ├── renderer.py           # Jinja2 渲染
│   └── resolver.py           # 变量解析
├── configs/                  # YAML 流程定义（按订单类型一份）
│   ├── mify-endpoint.yaml    # mify 平台连接配置
│   ├── znb-prpo.yaml         # ZNB 标准采购 PRPO
│   ├── znb-prpo-nouser.yaml  # ZNB 无物料信息
│   ├── zww-prpo.yaml         # ZWW 成品 PRPO
│   ├── zww-prpo-nouser.yaml  # ZWW 无物料信息
│   └── ...                   # 更多订单类型
├── templates/                # Jinja2 请求体模板
│   ├── znb-pr-body-v3.json.j2
│   ├── zww-pr-body-v3.json.j2
│   ├── prpo-params.json.j2
│   └── ...
├── shared/
│   └── common-steps.yaml     # 可复用的共享步骤（审批/查询/Cookie 等）
└── examples/                 # 脱敏测试 Case 集
```

## 7. 端到端示例

以 ZNB 标准采购订单为例，完整流程（精简展示关键步骤）：

```yaml
name: ZNB普通物料PRPO造单
description: 查询物料元数据 → ASL校验 → 创建PR → PR审批 → 查合同 → PR转PO → PO审批 → 查ERP单号

use:
  - common-steps.get_cookie

inputs:
  stockOrg:     { label: 库存组织, required: true, example: "MI_IOT" }
  purchaseOrg:  { label: 采购组织, required: true, example: "2120" }
  supplierCode: { label: 供应商编码, required: true }
  materials:    { label: 物料列表, required: true, type: object }
  shipLocCode:  { label: 发货地点, required: true }

steps:
  # ① 获取认证 Cookie（共享步骤）
  # ② 物料元数据查询与过滤（共享步骤）
  # ③ ASL 校验（共享步骤）

  # ④ 拼 PR 请求体
  - id: build_pr
    action: template
    template: "templates/znb-pr-body-v3.json.j2"
    context:
      stockOrg: "{{inputs.stockOrg}}"
      purchaseOrg: "{{inputs.purchaseOrg}}"
      supplierCode: "{{inputs.supplierCode}}"
      materials: "{{steps.filter_materials.output}}"

  # ⑤ 创建 PR
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

  # ⑥ 查 PR（含 retry/polling —— 等待异步落库）
  - id: query_pr_info
    action: sql_query
    wait: 5
    retry: { max: 8, interval_ms: 7000 }
    params:
      db_uri: "{{config.db_uri}}"
      query: "SELECT purchase_no, business_key FROM m_purchase WHERE ... ORDER BY id DESC LIMIT 1"
    extract:
      purchase_no: "$.rows[0].purchase_no"
      business_key: "$.rows[0].business_key"

  # ⑦ PR 审批（共享步骤）
  # ⑧ 查合同（共享步骤）
  # ⑨ PR 转 PO
  # ⑩ PO 审批（共享步骤）

  # ⑪ 查 ERP 单号（含 retry/polling）
  - id: query_erp
    action: sql_query
    retry: { max: 10, interval_ms: 10000 }
    params:
      db_uri: "{{config.db_uri}}"
      query: "SELECT erp_no FROM m_purchase_order WHERE purchase_order_no = '{{steps.query_po_info.extracted.purchase_order_no}}'"
    extract:
      erp_no: "$.rows[0].erp_no"

  # ⑫ 条件判断：有 ERP 单号则成功，否则重新推送
  - id: check_erp
    action: condition
    if: "{{steps.query_erp.extracted.erp_no}} != ''"
    then: SUCCESS
    else: repush_erp

terminals:
  SUCCESS:
    type: success
    message: |
      PR号: {{steps.query_pr_info.extracted.purchase_no}}
      PO号: {{steps.query_po_info.extracted.purchase_order_no}}
      ERP单号: {{steps.query_erp.extracted.erp_no}}
  END_PO_FAIL:
    type: error
    message: "PO创建失败: {{steps.pr_to_po.extracted.message}}"
```

## 8. 两种执行模式

| 模式 | 适用场景 | 行为 |
|------|---------|------|
| **向导执行** | 汇报 / 排障 / 新人学习 | 逐步展示每阶段结果，等用户确认再继续 |
| **静默执行** | 日常高频造数 | 一键跑完，只展示最终结果卡 |

切换方式：用户说"一步步来"或"逐步执行"进入向导模式；说"直接跑"或"静默"进入静默模式。默认向导模式。

## 9. 健壮性能力（失败路径）

| 能力 | 解决什么 |
|------|---------|
| **静态校验** | 执行前检查 step id 唯一性、goto 目标存在性、模板文件存在性、collect 命名冲突 |
| **状态快照** | 中间步骤保存上下文，第 N 步失败可知前序全过程，支持断点诊断 |
| **重试策略** | 异步链路智能等待与轮询（retry + interval_ms），用于审批/ERP 推送等异步场景 |
| **日志脱敏** | 敏感信息（密码、Token）自动遮蔽，安全可追溯 |
| **防无限循环** | goto 目标静态校验 + loop 循环次数上限，防止死循环 |
| **条件降级** | `on_error` 字段定义失败时的友好提示，非静默崩溃 |

## 10. 输入/输出契约

**输入**：自然语言诉求（可多轮补齐），最终收敛为结构化参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| orderType | enum | 是 | 订单类型（ZNB/ZWW/ZDO/ZSC 等） |
| stockOrg | string | 是 | 库存组织编码 |
| purchaseOrg | string | 是 | 采购组织编码 |
| supplierCode | string | 是 | 供应商编码 |
| materials | object | 是 | 物料编码 → 数量映射 |
| projectCode | string | 否 | 项目编码 |
| shipLocCode | string | 条件必填 | 发货地点 |

**输出**：结构化结果卡片，字段包括：
- 采购申请号（PR No.）
- 采购订单号（PO No.）
- ERP 推送单号
- 审批状态
- 执行耗时
- 异常时：失败步骤 ID + 错误信息 + 可操作建议

## 11. 配置项

| 配置 | 环境变量 | 说明 |
|------|---------|------|
| Mify API 端点 | `MIFY_ENDPOINT` | 调用 mify 工作流平台 |
| Mify API Token | `MIFY_HTTP_TOKEN` | Bearer 认证 |
| MySQL 连接串 | `MIFY_DB_URI` | SQL 查询/写入 |
| SCM 基址 | `SCM_BASE_URL` | 采购系统接口 |
| BPM 审批地址 | `BPM_APPROVE_URL` | 审批系统接口 |
| Cookie 获取地址 | `SCM_COOKIE_URL` | 认证 Cookie |

**调用格式：**
```json
{
  "inputs": { "url": "...", "method": "POST", "headers": "{}", "body": "" },
  "user": "skill-runner",
  "response_mode": "streaming"
}
```

**返回格式（SSE streaming）：**
- `workflow_started` → 开始
- `node_finished` → 每个节点完成，含 outputs
- `workflow_finished` → 结束，outputs 包含最终结果（body, status_code）

### 采购组织映射表

| 采购组织中文名 | stockOrg | purchaseOrg |
|---------------|----------|-------------|
| 生态链 | MI_IOT | 2120 |
| 手机 | MI_PHONE | 1110 |
| 可穿戴 | MI_WEAR | 111J |
| 笔记本 | MI_NOTEBOOK | 111K |
| 空调 | MI_AIRCONDITION | 1131 |
| 电视 | MI_TV | 1111 |
| 空调M5 | MI_AIRCONDITION_M5 | 1134 |
| 冰箱 | MI_REFRIGERATOR | 1132 |
| 洗衣机 | MI_LAUNDRYCARE | 1133 |
| 汽车电子 | MI_AUTOEACC | 111N |

> 此映射表为唯一权威来源。`prompt.md` 中如有重复映射，以本文件为准。

## 12. 安全与合规

- **仅写入测试环境**，不接触生产数据库和生产接口。
- **全链路日志脱敏**：密码、Token、Cookie 自动遮蔽，安全可追溯。
- **执行前确认闸门**：防止 Agent 猜测关键字段导致脏数据。
- **凭证外部化**：所有敏感信息通过环境变量注入，SKILL.md 和 configs 不含真实凭证。
- **`sql_execute` 写操作**须经用户确认闸门，禁止静默执行。

## 13. 限制与边界

**当前覆盖：**
- 采购订单核心链路：ZNB 标准采购、ZWW 成品采购（PRPO 全流程）
- 4 种方法 × 已上线/待接入状态

**未覆盖（诚实声明）：**
- 合同造数、付款造数、库存全链路（见未来规划）
- 寄售、跨公司、委外等非标准订单类型（配置已预留，尚未接入）
- 多行物料批量造数（当前单次 1 条链路）

**外部依赖：**
- 依赖被测系统接口稳定性；接口大改需同步更新对应 YAML/模板
- 依赖 mify 平台可用性
- 审批和 ERP 推送为异步操作，受环境性能影响，极端情况可能超时

---

## 支持的方法（对话层 → 执行层映射）

| 对话层方法 | 材料类型 | 物料信息 | 状态 | 执行命令 |
|-----------|---------|---------|------|---------|
| `getPRPOPULLByUser` | 原材料/半成品 | 已准备 | ✅ 已上线 | `engine.py configs/znb-prpo.yaml --...` |
| `getPRPOPULLNoUser` | 原材料/半成品 | 未准备 | ⚠️ 待接入 | 须明确告知"该场景暂未上线" |
| `getPRPOZWWByUser` | 成品 | 已准备 | ✅ 已上线 | `engine.py configs/zww-prpo.yaml --...` |
| `getZWWPRPONoUsers` | 成品 | 未准备 | ⚠️ 待接入 | 须明确告知"该场景暂未上线" |

> 标记为"待接入"的方法，当用户触发时必须明确告知"该场景尚未上线，暂不支持"，禁止尝试执行或给出模糊回复。

## 使用方式

### 对话式（推荐）

```
用户：帮我造一条生态链的标准采购订单

Agent：已识别场景：ZNB 标准采购订单造数
      还需要：供应商编码、物料信息、发货地点

用户：供应商 108062，物料 1710301000006A，发货地点 129797

Agent：请确认本次造数参数：
      - 订单类型：ZNB 标准采购
      - 采购组织：生态链（MI_IOT / 2120）
      - 供应商编码：108062
      - 物料：1710301000006A × 1
      - 发货地点：129797
      确认后开始执行。

用户：确认

Agent：✅ 执行完成（耗时约 3 分钟）
      - 采购申请号：PR-XXXXXXXX
      - 采购订单号：PO-XXXXXXXX
      - ERP 推送单号：已回写，状态正常
```

### 命令式

```bash
cd ~/.openclaw/workspace/skills/mify-data-factory
python3 engine.py configs/znb-prpo.yaml \
  --stockOrg MI_IOT \
  --purchaseOrg 2120 \
  --supplierCode 108062 \
  --materials '{"materialCode1": "1710301000006A"}' \
  --shipLocCode 129797
```

## 新增造单场景

只需要：
1. 写一个新的 `configs/xxx.yaml`（流程配置，声明式）
2. 写对应的 Jinja2 模板（如需要）
3. 在 `prompt.md` 中补充方法映射
4. **不改任何 Python 代码！**

`engine.py` 是通用编排引擎，自动读 YAML → 调 mify → 解析返回 → 条件分支/循环。

## 质量基线

最近一次 SkillSentry 测评结果（2026-06-17）：
- 测试用例：8 条，断言通过率 44/44 = **100%**
- 覆盖场景：4 种方法 × 3 种状态 = 12 种组合
- 评级：**PASS**（凭证外部化修复后）
