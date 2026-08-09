# 源工作流归档（references/workflows）

本目录归档 DataForge Loop v5 跨系统全链路所参考的 Dify/平台工作流导出件，作为**血缘留痕**。
它们不参与运行时执行——运行时逻辑已收口进 `configs/` + `tools/`。保留原始导出便于回溯"某个场景/节点是从哪条工作流沉淀而来"。

| 归档文件 | 来源工作流 | 在 DataForge Loop 中的落位 |
|---------|-----------|--------------------------|
| `srm-sourcing-price.source.yml` | SRM 寻源价格造数 | 阶段0 前置治理 → `configs/srm-price-clean.yaml` + `shared/srm-price-steps.yaml` + `tools/srm_price_clean.py` |
| `srm-asn-robot.source.yml` | SRM ASN 建单机器人（60+ 节点） | 阶段3 ASN 承接 → `configs/srm-asn-create.yaml` + `shared/asn-steps.yaml` + `templates/asn-scene.json.j2` + `tools/srm_asn_create.py` |
| `data-governance-engine.source.yml` | 数据治理自动化引擎 | 连接范式参考（如何把治理步骤串成前置闸门） |

## 收口方式说明

- **寻源价格造数**：原工作流的价格检测 / ASL 创建 / 费用项造价 / 定价单重推等节点，
  被拆成声明式步骤（`shared/srm-price-steps.yaml`）+ 分支配置（`configs/srm-price-clean.yaml`），
  由 10-Action 引擎执行。machine_fee 强制造价分支用 `condition + contains` 命中、`noop` 显式终止（早期 http_call 会吞掉 goto，根因已在引擎层修正，noop 收尾点保留作显式终止）。
- **ASN 建单机器人**：原工作流 60+ 节点的「按供应商类型×行数判断走哪条建单路径」逻辑，
  收口为 `tools/srm_asn_create.py::resolve_category / resolve_scene` 的类别与场景解析，
  真正的建单调用统一走平台原生 `datacube scene/execute`（异构于 SAP-YAML 引擎，但复用同一套三道闸 + 证据包）。

> 脱敏说明：这些导出件含真实系统/接口/供应商信息，仅供内部血缘追溯，**不得进入对外分享材料**。
