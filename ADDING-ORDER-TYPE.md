# AI 数据智造引擎 - 新业务线接入指南

## 概述

本指南说明如何为新的订单类型（如 ZWW、ZABC 等）接入 AI 数据智造引擎。

## 接入步骤

### Step 1: 准备工作

确认你有该业务线的 mify 工作流导出 YAML，了解：
- 创建 PR 的 SCM 接口 URL
- 是否需要代工厂查询
- 是否需要配额处理
- 合同查询的特殊条件

### Step 2: 创建流程配置

复制最接近的基础配置：

```bash
# 如果不需要代工厂和配额（最简流程）
cp configs/zdo-prpo.yaml configs/{你的订单类型}-prpo.yaml

# 如果需要代工厂和配额
cp configs/zsc-prpo.yaml configs/{你的订单类型}-prpo.yaml
```

然后修改：
1. **顶部 `name` 和 `description`**
2. **创建 PR 的 URL**（`create_pr` 步骤中的 `url`）
3. **合同查询条件**（如有差异，如 `price_type`）
4. **其他业务特定步骤**

### Step 3: 创建 PR 请求体模板（如需要）

如果新业务线的 PR 请求体结构与现有不同：

```bash
cp templates/pr-body.json.j2 templates/{订单类型}-pr-body.json.j2
```

修改模板中的字段差异。

如果请求体结构相同，直接复用 `pr-body.json.j2`。

### Step 4: 注册路由

在 `configs/router.yaml` 的 `routes` 中添加：

```yaml
routes:
  ZNB: "configs/znb-prpo.yaml"
  ZSC: "configs/zsc-prpo.yaml"
  ZYZ: "configs/zyz-prpo.yaml"
  ZDO: "configs/zdo-prpo.yaml"
  你的订单类型: "configs/你的订单类型-prpo.yaml"  # ← 加这一行
```

### Step 5: 更新对话层（可选）

在 `prompt.md` 的方法映射表中添加新行。

### Step 6: 添加飞书表格数据

在造单测试数据飞书表格中添加新业务线的数据行。

## 配置文件命名规范

```
{订单类型小写}-prpo.yaml
```

例如：
- `znb-prpo.yaml` → ZNB 订单
- `zsc-prpo.yaml` → ZSC 订单
- `zww-prpo.yaml` → ZWW 订单
- `zabc-prpo.yaml` → ZABC 订单

## 测试

```bash
cd ~/.openclaw/workspace/skills/mify-data-factory
python3 engine.py configs/{订单类型}-prpo.yaml \
  --stockOrg MI_IOT \
  --purchaseOrg 2120 \
  --supplierCode 108062 \
  --materials '{"materialCode1": "1710301000006B"}' \
  --projectCode "EcoOdmJdm20240708220947-EU" \
  --shipLocCode CN01
```

看到 `🎉 造单成功！` 及 PR/PO/ERP 单号即接入成功。

## engine.py 支持的 action

| action | 说明 | 何时使用 |
|--------|------|---------|
| `http_call` | 通过 mify 调 HTTP 接口 | 调 SCM/BPM 等外部接口 |
| `sql_query` | 执行 SQL 查询 | 查 PR、PO、合同等数据 |
| `template` | 渲染 Jinja2 模板 | 拼请求体 |
| `condition` | 条件分支（if/else） | 校验结果判断 |
| `switch` | 多路分支 | 按采购组织走不同流程 |
| `loop` | 循环遍历 | 遍历物料查合同/ASL |
| `route` | 路由到子流程 | 按订单类型分发 |

## 常见问题

### Q: 新业务线的 PR 请求体结构完全不同怎么办？
A: 创建新的 Jinja2 模板，在 YAML 中 `template` 字段指向新模板。

### Q: 新业务线不需要 PR 审批怎么办？
A: 在 YAML 中删除 `approve_pr` 步骤，把 `check_pr` 的 `then` 直接指向 `query_items`。

### Q: 新业务线的 ERP 推送逻辑不同怎么办？
A: 修改 `repush_erp` 步骤中的 URL 和参数。

### Q: 多个业务线共用同一个创建 PR 接口怎么办？
A: 在 YAML 中用 `condition` 或 `switch` 根据 `purchaseOrg` 区分。
