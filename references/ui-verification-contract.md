# UI 验收契约

## 目标

造数完成后，使用 Python Playwright 打开目标系统页面，按配置执行查询、点击、断言和截图，证明数据不是“接口返回成功”，而是“页面可查、业务可用”。

## 配置文件

默认配置：`configs/ui-verify-prpo.yaml`

核心字段：

- `base_url`：目标系统入口，可用 `${SCM_BASE_URL}` 从环境变量读取。
- `url`：验收页面路径。
- `steps`：浏览器操作步骤，支持 `fill`、`click`、`press`、`wait_for_selector`、`wait`、`assert_text`。
- `headless`：是否无头运行。

## 产物

- `ui-verify-result.json`：结构化验收结果。
- `screenshots/step-*.png`：成功步骤截图。
- `screenshots/failed-*.png`：失败步骤截图。

