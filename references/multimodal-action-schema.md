# OpenClaw 多模态动作 Schema

`ai-dataforge-loop` 接收 OpenClaw 原生多模态模型输出的 JSON，并将其转为造数参数、前置清洗动作或失败诊断动作。

## 标准字段

| 字段 | 说明 |
|---|---|
| `taskType` | `intent_extract` / `failure_diagnose` / `pre_clean_diagnose` / `ui_verify` |
| `sceneType` | 订单类型，如 `ZNB`、`ZSC`、`ZYZ`、`ZDO`、`ZWW` |
| `stockOrg` | 库存组织英文代码 |
| `purchaseOrg` | 采购组织代码 |
| `supplierCode` | 供应商编码 |
| `materials` | 多物料数组 |
| `projectCode` | 项目号 |
| `shipLocCode` | 发货地点 |
| `detectedIssues` | 失败/前置数据缺口列表 |
| `repairAction` | 修复动作 |
| `nextAction` | 下游动作 |
| `canProceedToDatamake` | 是否可直接进入造数 |
| `missingFields` | 缺失字段 |
| `confidence` | 识别置信度 |

## nextAction

| nextAction | Skill 行为 |
|---|---|
| `ASK_MISSING_FIELDS` | 继续追问缺失字段 |
| `AUTO_FILL_FROM_POOL` | 从测试数据池/默认样例补齐非关键字段 |
| `RUN_PRE_CLEAN` | 执行 `tools/srm_price_clean.py` |
| `RUN_DATAMAKE` | 执行 `tools/datamake_runner.py` |

## repairAction

| repairAction | 对应处理 |
|---|---|
| `CREATE_ASL` | 走前置清洗中的 ASL 修复 |
| `BIND_COST_PN` | 走前置清洗中的费用 PN 绑定 |
| `CONFIG_COST_ITEM` | 走前置清洗中的费用项配置 |
| `CREATE_PRICE_LIST` | 走前置清洗中的定价单创建 |
| `REPUSH_ERP` | 走 ERP 重推/状态回查 |
| `CHECK_CONTRACT_OR_RESELECT_DATA` | 追问用户或从测试数据池重选 |
| `CHECK_QUERY_CONDITION` | 追问查询条件 |
| `REFRESH_LOGIN` | 提示刷新登录态 |
| `CHECK_PERMISSION` | 提示检查权限 |

