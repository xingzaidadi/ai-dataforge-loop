---
name: ai-dataforge-loop
display_name: AI 数据智造闭环引擎(DataForge Loop)
version: 4.2.0
description: |
  AI 数据智造闭环引擎:面向供应链测试场景,支持从文本、SOP、页面截图中识别造数需求,自动收口参数、执行 PRPO 造数、发起 UI 截图验收,并生成 HTML 证据包与失败诊断。
  触发场景:用户说"帮我造单""造一条采购订单""PRPO拉料""帮我造数""看这个截图帮我造测试数据""按这个SOP造数""造完帮我页面验收""分析这张失败截图"等造数闭环相关请求。
  不触发场景:查询已有订单状态、报销、审批、查物料信息、问接口文档、编写通用 UI 自动化测试用例。
author: MI
track: C-跨部门协同
platform: 工作虾(Open Claw)
spec: MIT AI Skill 撰写规范 V1.1-beta
tags: [造数, 测试数据, 供应链, 流程编排, Agent, 多模态, UI验收, PRPO]
---

# AI 数据智造闭环引擎(DataForge Loop)

> 从一句业务诉求或一张页面截图,到一条可验证、可追溯、可诊断的供应链数据链路。

## 1. 问题描述

在复杂供应链业务里,一条可用的测试数据要跨 **7+ 系统、40+ 步操作**,涉及采购、审批、ERP、QA、DBA 多方协同。这套协同知识通常只存在于少数熟手脑中,人一走经验就断。

传统做法的困境:
- **手工造数**:单场景 1-3 人天,严重依赖个人经验
- **脚本自动化**:每个场景独立一套脚本,复制粘贴改参数,维护成本随场景数指数增长
- **低代码平台**:节点越加越多,分支越连越乱,变成谁也不敢动的"节点巨图"

DataForge Loop 把这条"长在人脑里"的协同链路,沉淀为**机器可执行、团队可复用、新人可接手**的能力。

## 2. 触发场景

**触发**--当用户表达以下意图时调用:
- "帮我造一条 XX 采购订单"
- "ZNB 造单""ZWW 造单""PRPO 拉料"
- "造一批测试数据""准备一条全链路测试数据"
- "生态链的标准采购订单造一条"
- "看这张页面截图,帮我判断要造什么数据"
- "按这个 SOP 截图/文档生成测试数据"
- "造完后帮我打开页面验收并留截图"
- "分析这张失败截图,告诉我卡在哪一步"
- 任何"构造一条需要跨多个系统、带状态流转的业务测试数据"的诉求

**不触发**--以下场景明确不归本 Skill 管:
- 只读查询("查下这条订单状态")
- 纯接口调试("帮我调下这个接口")
- 报销、审批等与造数无关的对话
- 查物料信息、问接口文档
- 只要求生成通用 Playwright 自动化用例、但不涉及造数闭环

## 3. 首次响应规则(强制)

当用户触发本 Skill 时,**第一轮回复必须展示多模态入口菜单**(见 prompt.md 阶段 0):

```
👋 AI 数据智造引擎(DataForge Loop)

请选择造数方式:

📝 1. 文字描述 - 告诉我你要造什么数据
📸 2. 截图识别 - 发 SCM/SOP/失败截图,我自动提取参数
🔧 3. 直接执行 - 已有参数,直接跑造数流程

也可直接说:
• "帮我造一条生态链 ZNB PRPO"
• "按这张截图帮我造数"(附截图)
• "造数失败了,看下怎么修"(附失败截图)
```

**规则**:
- 禁止跳过此菜单直接追问参数
- 禁止跳过此菜单直接执行造数
- 用户直接发截图 → 自动走截图识别流程,无需再展示菜单
- 用户直接说造数意图 → 展示菜单并识别意图

---

## 4. 交互契约(三道闸)

### 闸 1:必填校验

参数不完整时禁止执行,必须追问补齐:
- 订单类型(ZNB/ZWW/ZDO 等)
- 采购组织
- 供应商编码
- 物料信息(物料编码 + 数量)

条件必填--不同订单类型动态追加:寄售 → 供应商库存地 | 跨公司 → 收发公司编码 | 委外 → 工序路线。

### 闸 2:执行前确认

参数齐备后,必须生成参数确认卡片,逐项列出最终参数。用户回复"确认"后才执行;拒绝或沉默时中止并告知"已取消"。

### 闸 3:业务映射 & 脱敏

- Agent 负责把口语化业务词映射为系统字段(见采购组织映射表),禁止让用户自己查编码。
- 输出中禁止暴露数据库密码、API Token 等凭证;只展示业务数据(单号、状态),不展示原始 HTTP 响应体。

## 5. 五层架构

```
┌─────────────────────────────────────────────────┐
│  AI Agent 多模态入口 - 文本 / SOP / 截图 / 失败图   │  ← 降低使用门槛
├─────────────────────────────────────────────────┤
│  闭环编排层 - 识别 / 造数 / UI验收 / 诊断 / 证据包  │  ← 过程可追溯
├─────────────────────────────────────────────────┤
│  Python 编排引擎 - 条件 / 循环 / 路由 / 重试 / 状态 │  ← 流程可测试、可版本化
├─────────────────────────────────────────────────┤
│  YAML 配置层 - 声明式描述业务流程差异              │  ← 新增场景只改配置
├─────────────────────────────────────────────────┤
│  Jinja2 模板层 - 复杂请求体结构化治理             │  ← 请求结构可审查
├─────────────────────────────────────────────────┤
│  执行层(HTTP + SQL)- 薄执行通道                │  ← 稳定、简单、易替换
└─────────────────────────────────────────────────┘
```

| 层 | 文件 | 职责 |
|---|------|------|
| **对话层** | `prompt.md` | 收集参数、确认、映射转换、格式化输出 |
| **闭环编排层** | `tools/closed_loop_runner.py` | 统一 run_id,串联意图识别、造数、UI 验收、失败诊断、证据包 |
| **编排引擎** | `engine.py` | 读 YAML、执行 9 种 Action、管理状态/重试/分支 |
| **YAML 配置层** | `configs/*.yaml` | 声明式描述每种订单的完整流程步骤 |
| **模板层** | `templates/*.j2` | Jinja2 渲染复杂请求体 |
| **执行层** | mify 平台 | 只提供 `http_call` 和 `sql_query` 两个通用工具 |

### 多模态闭环

```text
文本/截图/SOP
  → tools/vision_extract.py 提取造数意图
  → 参数缺失时继续追问,参数齐备后执行确认闸
  → tools/datamake_runner.py 调用现有 engine.py
  → tools/ui_verify.py 使用 Python Playwright 页面验收并截图
  → 失败时 tools/failure_diagnose.py 生成诊断建议
  → tools/evidence_pack.py 输出 report.html 和结构化 JSON
```

关键原则:多模态能力只做外层增强,不改 `engine.py` 主干;识别失败时回退为文本追问,UI 验收失败时保留造数结果并标记 `PARTIAL`。

**截图识别后自动补全规则**(不询问用户,直接执行):
- **供应商编码自动映射**:截图中显示供应商公司名时,根据采购组织从已知映射表匹配编码(如生态链 + 威海弘霖电子 → 108062),映射表无匹配时才追问
- **已有 PR 识别**:截图中若显示 PR 单号(如 8440027538)且状态为「已通过」或「审批中」,说明是已存在的 PR,不追问已提取字段,shipLocCode 等条件必填字段若截图未显示视为已具备

### ⚠️ 飞书图片强制路由（不可跳过）

当飞书消息包含图片时，**无论是否同时附带文字描述（Description）**，必须：

1. **仅以图片为输入**，调用 `mimo-omni` 视觉模型，禁止跳过
2. **禁止使用 OpenClaw 预处理的文字描述（Description）作为造数参数来源**——文字描述只是飞书通道的副产物，仅供人类阅读参考，不参与参数提取
3. 输出格式严格遵循 `prompts/screenshot-to-params.md` 定义的 JSON schema
4. 再经 `tools/screenshot_params_adapter.py` 转换后，按固定格式展示识别结果

> ❌ 违规示例：收到图片+Description 后直接从 Description 提取参数拼输出
> ✅ 正确做法：无视 Description，调 mimo-omni 识别图片 → adapter 转换 → 固定格式输出

### OpenClaw 原生多模态接入

当用户在飞书/OpenClaw 中上传 SCM、SRM、PR、PO、SOP 或失败截图时,**必须调用 mimo-omni 视觉模型脚本**(禁止用 OpenClaw 预处理的文字描述代替):

```bash
cd ~/.openclaw/workspace/skills/ai-dataforge-loop
python3 ~/.openclaw/plugin-skills/mimo-omni/scripts/mimo_api.py \
  image <图片路径> "$(cat prompts/screenshot-to-params.md)" --timeout 120
```

输出结构化 JSON 后,通过 `tools/screenshot_params_adapter.py` 转成 `engine.py` 可消费的造数参数。

```text
飞书图片 + 用户诉求
  → OpenClaw 原生多模态模型按 prompts/screenshot-to-params.md 输出 JSON
  → tools/screenshot_params_adapter.py 统一字段、组织映射、多物料数组和 nextAction
  → tools/closed_loop_runner.py --screenshot-json xxx.json 合并最终参数
  → RUN_DATAMAKE / RUN_PRE_CLEAN / ASK_MISSING_FIELDS 分流
  → report.html 展示"截图识别 → 参数收口 → 造数执行 → 证据报告"
```

命令示例:

```bash
python tools/closed_loop_runner.py \
  --config configs/znb-prpo.yaml \
  --ui-config configs/ui-verify-prpo.yaml \
  --screenshot-json evidence/screenshot-input.json \
  --text "根据飞书上传的 SCM 截图自动造数" \
  --dry-run
```

边界说明:本仓库不在 Python 内部直接调用视觉大模型;真正的图片理解由 OpenClaw/飞书通道完成。本 Skill 负责提供 Prompt、字段契约、参数适配、执行编排和报告留痕,避免云端 OpenClaw 无浏览器权限时依赖 Playwright。

## 6. 流程 DSL:9 种 Action

| Action | 作用 | 调执行层 |
|--------|------|---------|
| `http_call` | 通过 mify 调 HTTP 接口 | 是 |
| `sql_query` | 查询数据库状态 | 是 |
| `sql_execute` | 数据修正(配额/状态补齐),写操作须经确认闸 | 是 |
| `template` | 渲染 Jinja2 模板为请求体 | 否 |
| `condition` | 条件分支(if/then/else) | 否 |
| `switch` | 多路分支(switch_on/cases) | 否 |
| `loop` | 循环遍历(items/collect) | 间接 |
| `route` | 路由到子流程(orderType/routes) | 否 |
| `filter_collection` | 集合过滤(source/match_field) | 否 |

## 7. 目录结构

```
ai-dataforge-loop/
├── SKILL.md            # 本文件(技能声明)
├── prompt.md           # 对话层提示词
├── engine.py           # 通用编排引擎
├── tools/              # 多模态闭环工具(识别/验收/诊断/证据包)
├── lib/                # 引擎核心模块(client/config/flow/renderer/resolver)
├── configs/            # YAML 流程定义(znb-prpo.yaml, zww-prpo.yaml, ...)
├── templates/          # Jinja2 请求体模板
├── shared/             # 可复用共享步骤(审批/查询/Cookie)
├── references/         # 多模态契约、UI 验收契约、证据包结构
├── mify-apps/          # mify 平台工具定义(http-call/sql-query)
└── runners/            # 安全执行器
```

## 8. 端到端示例

以 ZNB 标准采购订单为例(完整 YAML 见 `configs/znb-prpo-v4.yaml`):

```yaml
name: ZNB普通物料PRPO造单
description: 查询物料元数据 → ASL校验 → 创建PR → PR审批 → 查合同 → PR转PO → PO审批 → 查ERP单号
use: [common-steps.get_cookie]
inputs:
  stockOrg:     { label: 库存组织, required: true, example: "MI_IOT" }
  purchaseOrg:  { label: 采购组织, required: true, example: "2120" }
  supplierCode: { label: 供应商编码, required: true }
  materials:    { label: 物料列表, required: true, type: object }
  shipLocCode:  { label: 发货地点, required: false }  # ZNB 不需要; ZSC/ZYZ/ZDO 为 true
steps:
  - id: build_pr            # 4 拼 PR 请求体
    action: template
    template: "templates/znb-pr-body-v3.json.j2"
  - id: create_pr           # 5 创建 PR
    action: http_call
    params: { url: "{{config.scm_base}}/mrp/pr/ordinary", method: POST }
  - id: query_pr_info       # 6 查 PR(含 retry/polling)
    action: sql_query
    retry: { max: 8, interval_ms: 7000 }
  - id: check_erp           # 12 条件判断
    action: condition
    if: "{{steps.query_erp.extracted.erp_no}} != ''"
    then: SUCCESS
    else: repush_erp
terminals:
  SUCCESS: { type: success, message: "PR号/PO号/ERP单号: ..." }
  END_PO_FAIL: { type: error, message: "PO创建失败" }
```

## 9. 两种执行模式

| 模式 | 适用场景 | 行为 |
|------|---------|------|
| **向导执行** | 汇报 / 排障 / 新人学习 | 逐步展示每阶段结果,等用户确认再继续 |
| **静默执行** | 日常高频造数 | 一键跑完,只展示最终结果卡 |
| **闭环执行** | 验收留痕 / 失败诊断 / 闭环回放 | 从文本、SOP 或截图识别需求,执行造数,打开页面截图验收,生成证据包 |

切换方式:用户说"一步步来"或"逐步执行"进入向导模式;说"直接跑"或"静默"进入静默模式。默认向导模式。

**⚠️ 所有模式必须跑完全链路**:造数 = PR创建 → PR审批 → 查合同 → PR转PO → PO审批 → 查ERP单号。绝对不允许只创建PR就停下。最终结果必须包含 PR号 + PO号 + ERP单号。

闭环执行命令示例:

```bash
python tools/closed_loop_runner.py \
  --text "帮我造一条生态链 ZNB PRPO,造完做页面验收" \
  --config configs/znb-prpo.yaml \
  --ui-config configs/ui-verify-prpo.yaml \
  orderType=ZNB purchaseOrg=2120 stockOrg=MI_IOT supplierCode=SUPPLIER_DEMO \
  materials='{"materialCode1":"MAT_DEMO"}' projectCode=PROJECT_DEMO
```

预检或无真实环境时可加 `--dry-run`,跳过真实外部调用并生成 `evidence/runs/{run_id}/report.html` 证据包。

## 10. 健壮性能力(失败路径)

| 能力 | 解决什么 |
|------|---------|
| **静态校验** | 执行前检查 step id 唯一性、goto 目标存在性、模板文件存在性、collect 命名冲突 |
| **状态快照** | 中间步骤保存上下文,第 N 步失败可知前序全过程,支持断点诊断 |
| **重试策略** | 异步链路智能等待与轮询(retry + interval_ms),用于审批/ERP 推送等异步场景 |
| **日志脱敏** | 敏感信息(密码、Token)自动遮蔽,安全可追溯 |
| **防无限循环** | goto 目标静态校验 + loop 循环次数上限,防止死循环 |
| **条件降级** | `on_error` 字段定义失败时的友好提示,非静默崩溃 |

## 11. 输入/输出契约

**输入**:自然语言诉求(可多轮补齐),最终收敛为结构化参数:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| orderType | enum | 是 | 订单类型(ZNB/ZWW/ZDO/ZSC 等) |
| stockOrg | string | 是 | 库存组织编码 |
| purchaseOrg | string | 是 | 采购组织编码 |
| supplierCode | string | 是 | 供应商编码 |
| materials | object | 是 | 物料编码 → 数量映射 |
| projectCode | string | 否 | 项目编码 |
| shipLocCode | string | 条件必填 | 发货地点（仅 ZSC/ZYZ/ZDO 必填；ZNB 不需要，模板未使用） |

**输出**:结构化结果卡片(成功时):

| 字段 | 类型 | 必含 | 说明 |
|------|------|------|------|
| prNo | string | 是 | 采购申请号 |
| poNo | string | 是 | 采购订单号 |
| erpNo | string | 是 | ERP 推送单号 |
| approvalStatus | enum | 是 | 已通过 / 审批中 / 已拒绝 |
| duration | string | 是 | 执行耗时(如"2分38秒") |
| stepsCompleted | string | 是 | 完成步骤(如"12/12") |

**输出**:结构化错误卡片(失败时):

| 字段 | 类型 | 必含 | 说明 |
|------|------|------|------|
| failedStep | string | 是 | 失败步骤 ID(如 pr_to_po) |
| errorCode | string | 是 | 错误码(如 BIZ_ERROR_3001) |
| errorMessage | string | 是 | 可读错误信息 |
| stepsCompleted | string | 是 | 已完成步骤(如"8/12") |
| suggestions | string[] | 是 | 可操作建议列表(1-3 条) |

## 12. 配置项

| 配置 | 环境变量 | 说明 |
|------|---------|------|
| Mify API 端点 | `MIFY_ENDPOINT` | 调用 mify 工作流平台 |
| Mify API Token | `MIFY_HTTP_TOKEN` | Bearer 认证 |
| MySQL 连接串 | `MIFY_DB_URI` | SQL 查询/写入 |
| SCM 基址 | `SCM_BASE_URL` | 采购系统接口 |
| BPM 审批地址 | `BPM_APPROVE_URL` | 审批系统接口 |
| Cookie 获取地址 | `SCM_COOKIE_URL` | 认证 Cookie |

调用方式:streaming SSE(`workflow_started` → `node_finished` → `workflow_finished`)。

### 采购组织映射表

| 中文名 | stockOrg | purchaseOrg |
|--------|----------|-------------|
| 生态链 | MI_IOT | 2120 |
| 手机 | MI_PHONE | 1110 |
| 可穿戴 | MI_WEAR | 111J |
| 笔记本 | MI_NOTEBOOK | 111K |
| 空调 | MI_AIRCONDITION | 1131 |
| 电视 | MI_TV | 1111 |

> 完整映射含 10 个组织,见 `configs/router.yaml`。此处为高频子集。

## 13. 安全与合规

- **仅写入测试环境**,不接触生产数据库和生产接口。
- **全链路日志脱敏**:密码、Token、Cookie 自动遮蔽。
- **执行前确认闸门**:所有写操作(含 `sql_execute`)须经用户确认,禁止静默执行。
- **凭证外部化**:敏感信息通过环境变量注入,代码仓库不含真实凭证。

## 14. 限制与边界

**当前覆盖:**
- 采购订单核心链路:ZNB 标准采购、ZWW 成品采购(PRPO 全流程)
- 4 种方法 × 已上线/待接入状态

**未覆盖(诚实声明):**
- 合同造数、付款造数、库存全链路(见未来规划)
- 寄售、跨公司、委外等非标准订单类型(配置已预留,尚未接入)
- 多行物料批量造数(当前单次 1 条链路)

**外部依赖:**
- 依赖被测系统接口稳定性;接口大改需同步更新对应 YAML/模板
- 依赖 mify 平台可用性
- 审批和 ERP 推送为异步操作,受环境性能影响,极端情况可能超时

---

### 支持的方法(对话层 → 执行层映射)

| 方法 | 材料类型 | 状态 | 行为 |
|------|---------|------|------|
| `getPRPOPULLByUser` | 原材料/半成品(物料已准备) | ✅ 已上线 | 执行 `configs/znb-prpo.yaml` |
| `getPRPOPULLNoUser` | 原材料/半成品(物料未准备) | ⚠️ 待接入 | 告知"该场景暂未上线" |
| `getPRPOZWWByUser` | 成品(物料已准备) | ✅ 已上线 | 执行 `configs/zww-prpo.yaml` |
| `getZWWPRPONoUsers` | 成品(物料未准备) | ⚠️ 待接入 | 告知"该场景暂未上线" |

> 待接入方法触发时,必须明确告知用户并拒绝执行。

### 对话示例(成功路径)

```
用户:帮我执行下 ai-dataforge-loop

Agent:👋 AI 数据智造引擎(DataForge Loop)

      请选择造数方式:

      📝 1. 文字描述 - 告诉我你要造什么数据
      📸 2. 截图识别 - 发 SCM/SOP/失败截图,我自动提取参数
      🔧 3. 直接执行 - 已有参数,直接跑造数流程

      也可直接说:
      • "帮我造一条生态链 ZNB PRPO"
      • "按这张截图帮我造数"(附截图)
      • "造数失败了,看下怎么修"(附失败截图)

用户:1,帮我造一条生态链的标准采购订单

Agent：已识别场景：ZNB 标准采购订单。
      还需要以下信息：
      ❌ 供应商编码
      ❌ 物料信息（编码 + 数量）
      请补充。
      
      （注：ZNB 场景不需要发货地点）

用户：供应商 SUPPLIER_DEMO，物料 MAT_DEMO_A 数量 1

Agent：📋 参数确认卡片
      ┌──────────────────────────────────┐
      │ 订单类型   │ ZNB 标准采购          │
      │ 采购组织   │ 生态链（MI_IOT / 2120）│
      │ 供应商编码 │ SUPPLIER_DEMO               │
      │ 物料      │ MAT_DEMO_A × 1    │
      │ 发货地点   │ 不需要（ZNB 场景跳过）  │
      └──────────────────────────────────┘
      请回复“确认”后开始执行造数流程。如需修改任何参数，请直接告知。

用户:确认

Agent:⏳ 执行中(预计 2-4 分钟)...
      ✅ 造数完成
      ┌──────────────────────────────────┐
      │ 采购申请号 │ PR-20260618001       │
      │ 采购订单号 │ PO-20260618001       │
      │ ERP单号   │ ERP_DEMO_001           │
      │ 审批状态   │ 已通过               │
      │ 执行耗时   │ 2分38秒             │
      └──────────────────────────────────┘
```

### 对话示例(失败路径)

```
用户:确认

Agent:⏳ 执行中...
      ❌ 执行失败(步骤 9 PR转PO)
      ┌──────────────────────────────────┐
      │ 失败步骤   │ pr_to_po             │
      │ 错误码    │ BIZ_ERROR_3001        │
      │ 错误信息   │ 合同未生效,无法转PO   │
      │ 已完成步骤 │ 12345678(8/12) │
      └──────────────────────────────────┘
      建议操作:
      1. 检查供应商 SUPPLIER_DEMO 在该采购组织下的合同状态
      2. 如需跳过合同校验,使用 ZDO 无合同订单类型重试
      是否需要我帮你排查?
```

### 对话示例(拒绝路径)

```
用户:帮我查下 PO-20260618001 的审批状态

Agent:这属于只读查询场景,不在造数 Skill 的管辖范围内。
      建议直接在 SCM 系统查询,或使用查询类工具。
```

### 性能预期

| 指标 | 数值 | 说明 |
|------|------|------|
| 单链路耗时 | 2-4 分钟 | ZNB/ZWW 全流程(含异步审批等待) |
| 超时上限 | 8 分钟 | 超过后中止并报告已完成步骤 |
| 单步重试上限 | 10 次 × 10s | 用于异步落库轮询(如 ERP 回写) |
| 并发限制 | 1 条/次 | 当前不支持批量并行造数 |
| 失败恢复 | 支持断点诊断 | 报告失败步骤 + 前序上下文,不支持自动续跑 |

### 使用方式

**对话式**(推荐):用户说"帮我造一条生态链的标准采购订单" → Agent 追问缺失参数 → 展示确认卡片 → 用户确认 → 执行出结果。

**命令式**(ZNB):`python3 engine.py configs/znb-prpo.yaml --stockOrg MI_IOT --purchaseOrg 2120 --supplierCode SUPPLIER_DEMO --materials '{"m1":"MAT_DEMO_A"}'`

> 注：ZNB 不传 --shipLocCode（模板不需要）。ZSC/ZYZ/ZDO 需要传。

### 新增造单场景

新增场景只需:1 写 `configs/xxx.yaml` 2 写对应 Jinja2 模板 3 在 `prompt.md` 补映射。不改 Python 代码。
