# AI 数据智造闭环引擎 (DataForge Loop)

> 从一句业务诉求或一张页面截图，到一条可验证、可追溯、可诊断的供应链数据链路。

## 项目简介

DataForge Loop 是面向供应链测试场景的 AI 数据智造引擎，支持：

- 📝 **文字描述** - 告诉我你要造什么数据
- 📸 **截图识别** - 发 SCM/SOP/失败截图，自动提取参数
- 🔧 **直接执行** - 已有参数，直接跑造数流程

## 核心能力

- **多模态入口**：支持文本、SOP、页面截图、失败截图
- **闭环编排**：识别 → 造数 → UI验收 → 诊断 → 证据包
- **声明式配置**：新增场景只改 YAML，不改 Python
- **逐步向导**：每步展示详细进度，支持截图汇报
- **失败诊断**：自动分析失败原因，提供修复建议

## 支持的订单类型

| 订单类型 | 场景 | 状态 |
|---------|------|------|
| ZNB | 标准采购订单 | ✅ 已上线 |
| ZSC | 试产采购订单 | ✅ 已上线 |
| ZYZ | 验证采购订单 | ✅ 已上线 |
| ZDO | 免费采购订单 | ✅ 已上线 |
| ZWW | 成品采购订单 | ✅ 已上线 |

## 快速开始

### 1. 环境配置

```bash
# 复制环境配置文件
cp .env.example .env

# 编辑 .env 文件，填入你的配置
```

### 2. 安装依赖

```bash
# 安装 Python 依赖
pip install -r requirements.txt
```

### 3. 执行造数

```bash
# 静默模式（推荐）
python engine.py configs/znb-prpo.yaml \
  --stockOrg MI_IOT \
  --purchaseOrg 2120 \
  --supplierCode SUPPLIER_DEMO \
  --materials '{"materialCode1":"MAT_DEMO_A"}' \
  --projectCode PROJECT_DEMO
```

## 目录结构

```
ai-dataforge-loop/
├── SKILL.md            # 技能声明
├── prompt.md           # 对话层提示词
├── engine.py           # 通用编排引擎
├── tools/              # 多模态闭环工具
├── lib/                # 引擎核心模块
├── configs/            # YAML 流程定义
├── templates/          # Jinja2 请求体模板
├── shared/             # 可复用共享步骤
├── references/         # 多模态契约、UI验收契约
├── mify-apps/          # mify 平台工具定义
└── runners/            # 安全执行器
```

## 五层架构

```
┌─────────────────────────────────────────────────┐
│  AI Agent 多模态入口 - 文本 / SOP / 截图 / 失败图   │
├─────────────────────────────────────────────────┤
│  闭环编排层 - 识别 / 造数 / UI验收 / 诊断 / 证据包  │
├─────────────────────────────────────────────────┤
│  Python 编排引擎 - 条件 / 循环 / 路由 / 重试 / 状态 │
├─────────────────────────────────────────────────┤
│  YAML 配置层 - 声明式描述业务流程差异              │
├─────────────────────────────────────────────────┤
│  Jinja2 模板层 - 复杂请求体结构化治理             │
├─────────────────────────────────────────────────┤
│  执行层(HTTP + SQL)- 薄执行通道                │
└─────────────────────────────────────────────────┘
```

## 使用方式

### 对话式（推荐）

```
用户: 帮我造一条生态链的标准采购订单

Agent: 已识别场景：ZNB 标准采购订单。
       还需要以下信息：
       ❌ 供应商编码
       ❌ 物料信息（编码 + 数量）
       请补充。
```

### 命令式

```bash
python engine.py configs/znb-prpo.yaml \
  --stockOrg MI_IOT \
  --purchaseOrg 2120 \
  --supplierCode SUPPLIER_DEMO \
  --materials '{"materialCode1":"MAT_DEMO_A"}' \
  --projectCode PROJECT_DEMO
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `MIFY_ENDPOINT` | Mify API 端点 | `https://service.mify.mioffice.cn/api/v1/workflows/run` |
| `MIFY_HTTP_TOKEN` | Mify API Token | `app-xxx` |
| `SCM_BASE_URL` | SCM 系统基址 | `https://scm.test.mioffice.cn` |
| `BPM_APPROVE_URL` | BPM 审批地址 | `https://bpm.test.mioffice.cn/approve` |
| `SCM_COOKIE_URL` | Cookie 获取地址 | `https://toolskit.test.mi.com/datacube/getSCMCookie` |

### 采购组织映射

| 中文名 | stockOrg | purchaseOrg |
|--------|----------|-------------|
| 生态链 | MI_IOT | 2120 |
| 手机 | MI_PHONE | 1110 |
| 可穿戴 | MI_WEAR | 111J |
| 笔记本 | MI_NOTEBOOK | 111K |
| 空调 | MI_AIRCONDITION | 1131 |
| 电视 | MI_TV | 1111 |

## 新增造单场景

1. 写 `configs/xxx.yaml`（流程配置）
2. 写 `templates/xxx.json.j2`（模板，可选）
3. 在 `prompt.md` 补映射

**不需要改 Python 代码！**

## 安全说明

- **仅写入测试环境**，不接触生产数据库和生产接口
- **全链路日志脱敏**：密码、Token、Cookie 自动遮蔽
- **凭证外部化**：敏感信息通过环境变量注入

## 贡献指南

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 联系方式

- 作者：刘四星
- 邮箱：liusixing@xiaomi.com
- GitHub：[@xingzaidadi](https://github.com/xingzaidadi)
