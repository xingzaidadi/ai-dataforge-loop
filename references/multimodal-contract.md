# 多模态造数输入契约

## 支持输入

- 文本：一句话造数需求，例如“帮我造一条生态链 ZNB PRPO”。
- SOP：页面操作步骤、测试说明、业务流程文档的文本版。
- 截图：页面截图、SOP 截图、失败截图；当前版本先提取文件线索与用户补充文本，真实 OCR/视觉模型可接入 Mify 工作流。

## 输出字段

```json
{
  "orderType": "ZNB",
  "stockOrg": "MI_IOT",
  "purchaseOrg": "2120",
  "supplierCode": "SUPPLIER_DEMO",
  "materials": {"materialCode1": "MAT_DEMO"},
  "projectCode": "PROJECT_DEMO"
}
```

## 降级策略

- 截图识别失败：回退为文本追问，不允许直接执行。
- 字段缺失：输出 `missingFields`，由 Agent 继续收口参数。
- 用户未确认：中止执行，避免误造数。

