# Mify 造数工厂 - 安装部署指南

## 概述

Mify 造数工厂是一个 OpenClaw Skill，通过飞书对话式交互，自动生成 SAP 测试数据（PR/PO/ERP 单号）。

当前配置化支持场景：
- ✅ ZNB 普通物料 PRPO 造单
- ✅ ZSC 试产 PRPO 造单
- ✅ ZYZ 验证物料 PRPO 造单
- ✅ ZDO 免费 PRPO 造单
- ✅ ZWW 成品委托 PRPO 造单
- ✅ ZWW 半成品 PRPO 造单

不同场景的业务阶段数量不同，配置展开后通常包含 10-30+ 个执行步骤。

## 安装步骤

### Step 1：复制 Skill 文件夹

将 `mify-data-factory/` 文件夹复制到 OpenClaw workspace 的 skills 目录下：

```
~/.openclaw/workspace/skills/mify-data-factory/
├── SKILL.md              # Skill 说明
├── prompt.md             # 对话层提示词（参数收集/确认/映射）
├── design.md             # 详细设计方案
├── engine.py             # 通用编排引擎
├── configs/
│   ├── mify-endpoint.yaml    # mify API 配置
│   └── znb-prpo.yaml         # ZNB PRPO 流程配置
└── templates/
    ├── pr-body.json.j2       # PR 请求体模板
    └── prpo-params.json.j2   # PR 转 PO 入参模板
```

### Step 2：配置 mify Token

编辑 `configs/mify-endpoint.yaml`，填入你的 mify API 凭证：

```yaml
endpoint: "${MIFY_ENDPOINT}"
token: "${MIFY_HTTP_TOKEN}"
sql_token: "${MIFY_SQL_TOKEN}"
workflow_id: "${MIFY_HTTP_WORKFLOW_ID}"
sql_workflow_id: "${MIFY_SQL_WORKFLOW_ID}"
user: "${MIFY_USER:-skill-runner}"
```

也可以参考 `.env.example` 在本机 shell 或 CI Secret 中设置环境变量。注意：`engine.py` 会自动拼接 `Authorization: Bearer <token>`，因此 `token` 只填写 `app-xxx`，不要写成 `Bearer app-xxx`。

### Step 3：配置飞书表格（可选）

如果你想用"从飞书表格获取"功能：

1. 复制一份造单测试数据飞书表格
2. 按照表格模板填入你的测试数据
3. 把表格 URL 填入 `prompt.md` 中的表格地址

表格模板列说明：

| 列名 | 说明 | 示例 |
|------|------|------|
| orderType | 订单类型 | ZNB, ZSC, ZDO, ZWW |
| materialTypeCN | 物料类型中文名 | 原材料, 成品, 半成品 |
| materialType | 物料类型英文 | material, finished, semi |
| purchaseOrgCN | 采购组织中文名 | 生态链, 手机, 可穿戴, 笔记本, 空调, 电视, 空调M5, 冰箱, 洗衣机, 汽车电子 |
| stockOrg | 库存组织 | MI_IOT, MI_PHONE, MI_WEAR 等 |
| purchaseOrg | 采购组织代码 | 2120, 1110, 111J 等 |
| supplierCode1 | 供应商编码 | 108062 |
| materialCode1 | 物料编码 | 1710301000006A |
| supplierCode2 | 第二供应商编码（可选） | 108062 |
| materialCode2 | 第二物料编码（可选） | 1710301000006B |
| SKU | SKU 编号（成品用） | ELA4130CN |
| projectCode | 项目编号 | EcoOdmJdm20240708220947-EU |
| shipLocCode | 发货地点 | CN01 |
| businessModel | 交料模式 | BS, CS |

### Step 4：安装 Python 依赖

```bash
pip install pyyaml requests jinja2 --break-system-packages
```

如需使用多模态闭环里的 UI 截图验收能力，继续安装 Python Playwright：

```bash
pip install playwright --break-system-packages
python -m playwright install chromium
```

### Step 5：验证安装

先执行静态校验，确认配置、模板、路由和敏感信息检查通过：

```bash
python3 scripts/validate_skill.py
```

静态校验不会真实调用 HTTP、SQL 或造单流程。

```bash
cd ~/.openclaw/workspace/skills/mify-data-factory
python3 engine.py configs/znb-prpo.yaml --stockOrg MI_IOT --purchaseOrg 2120 --supplierCode 108062 --materials '{"materialCode1": "1710301000006B"}' --projectCode "EcoOdmJdm20240708220947-EU" --shipLocCode CN01
```

看到 `🎉 造单成功！` 及 PR/PO/ERP 单号即安装成功。

验证多模态闭环外层编排（不真实造数、不打开浏览器）：

```bash
python3 tools/closed_loop_runner.py \
  --dry-run \
  --text "帮我造一条生态链 ZNB PRPO，造完做页面验收" \
  --config configs/znb-prpo.yaml \
  --ui-config configs/ui-verify-prpo.yaml \
  orderType=ZNB stockOrg=MI_IOT purchaseOrg=2120 supplierCode=SUPPLIER_DEMO \
  materials='{"materialCode1":"MAT_DEMO"}' projectCode=PROJECT_DEMO shipLocCode=LOC_DEMO
```

执行后会生成 `evidence/runs/{run_id}/report.html`、`summary.json`、`intent.json`、`datamake-result.json`、`ui-verify-result.json`。

## 使用方式

### 方式1：对话式（推荐）

在飞书中对 agent 说：

> "帮我造单"

agent 会引导你：
1. 选择材料类型（原材料/半成品/成品）
2. 选择数据来源（手工输入/系统自动/飞书表格）
3. 收集参数并确认
4. 自动执行造单

### 方式2：命令式

直接在终端执行：

```bash
cd ~/.openclaw/workspace/skills/mify-data-factory
python3 engine.py configs/znb-prpo.yaml \
  --stockOrg MI_IOT \
  --purchaseOrg 2120 \
  --supplierCode 108062 \
  --materials '{"materialCode1": "1710301000006B"}' \
  --projectCode "EcoOdmJdm20240708220947-EU" \
  --shipLocCode CN01
```

### 方式3：多模态闭环执行

适合参赛演示、验收留痕和失败诊断：

```bash
cd ~/.openclaw/workspace/skills/mify-data-factory
python3 tools/closed_loop_runner.py \
  --text "按这张页面截图帮我造一条生态链 ZNB PRPO，造完页面验收" \
  --image /path/to/page.png \
  --config configs/znb-prpo.yaml \
  --ui-config configs/ui-verify-prpo.yaml \
  orderType=ZNB stockOrg=MI_IOT purchaseOrg=2120 supplierCode=SUPPLIER_DEMO \
  materials='{"materialCode1":"MAT_DEMO"}' projectCode=PROJECT_DEMO shipLocCode=LOC_DEMO
```

如果 UI 验收失败，系统会保留造数结果，生成 `diagnosis.json` 和失败截图，整体状态标记为 `PARTIAL`。

## 采购组织映射表

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

## 新增业务线

如果需要新增造单场景（如 ZWW 成品造单）：

1. 新建 `configs/xxx.yaml`（复制 znb-prpo.yaml 修改）
2. 新建对应的 Jinja2 模板（如需要）
3. 在 `prompt.md` 方法映射表中添加新行
4. **不需要修改 Python 代码**

## 常见问题

### Q: SQL 报错 Unknown column 'create_at'
A: 表的时间列名可能不同，改用 `ORDER BY id DESC` 排序。

### Q: 查询到了历史数据而非新创建的单子
A: SQL 查询必须加 `ORDER BY id DESC LIMIT 1`，确保取最新数据。

### Q: Cookie 获取失败
A: 检查 `configs/mify-endpoint.yaml` 中的 token 是否过期。

### Q: BPM 审批报"额度不足"
A: BPM 接口有流控限制（10 per 1 minute），等一分钟后重试。

### Q: 执行时长太长
A: 正常执行约 46 秒。如果超时，检查网络连接和 mify 服务状态。
