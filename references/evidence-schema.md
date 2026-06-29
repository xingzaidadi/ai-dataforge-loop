# 闭环证据包结构

每次执行生成独立目录：

```text
evidence/runs/{run_id}/
├── intent.json
├── params.json
├── datamake-result.json
├── ui-verify-result.json
├── diagnosis.json
├── evidence-pack.json
├── summary.json
├── report.html
└── screenshots/
```

## 状态定义

- `SUCCESS`：造数成功，UI 验收通过。
- `PARTIAL`：造数成功，但 UI 验收失败或未完成，保留诊断建议。
- `FAILED`：造数主流程失败。
- `SKIPPED`：dry-run 预检模式跳过真实执行。

## 安全要求

- 证据包写入前统一脱敏 Token、数据库连接串、内部 URL。
- 对外材料只展示脱敏截图和脱敏 JSON。
- 真实凭证只允许存在于本机环境变量或未提交的 `.env`。
