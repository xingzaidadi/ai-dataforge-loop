# DataForge Loop 演示手册（DEMO.md）

> 本手册给出三条经过实测的演示路径，以及每条路径的真实成功状态。
> 原则：**能成功的说成功，卡住的如实说卡在哪** —— 演示时的诚实本身就是工程可信度。

---

## 0. 演示前速览：哪些真能建单？

| 环节 | 真实建单状态 | 演示可用性 |
|---|---|---|
| 阶段1 PRPO 造数（ZNB/ZWW） | ✅ **真出 PR→PO→ERP 单号** | 可现场演示真单号 |
| 阶段0 寻源价格前置治理 | ✅ 请求全 200 | 可演示 |
| 阶段3 ASN 承接 | ⚠️ 格式全对、全 200，**真实建单卡在 SAP PI 中间件后端**（`BubbleException`）| 演示"格式贯通"，如实说明后端阻塞 |
| 截图造单（A 路径） | ✅ 参数收口链实测通过（读图由平台 mimo-omni 承担）| 在 Mico 平台内演示 |
| 待接入方法 / ASN 长尾场景 | ❌ 明确拒绝或标 `resolved=False` | 演示"不谎报"原则 |

**一句话：** PRPO 主链路真能建单；ASN 代码/格式全通、真实建单被 SAP 后端阻塞；长尾场景诚实标记未接入。

---

## 演示一：全链路 dry-run（零风险，100% 可复现）

**用途：** 给业务/领导看完整闭环，不碰真实环境，稳定可复现。

```bash
python tools/closed_loop_runner.py \
  --text "高通单行全链路造数，从寻源到 ASN" \
  --config configs/znb-prpo.yaml \
  --pre-clean-config configs/srm-price-clean.yaml \
  --asn-config configs/srm-asn-create.yaml \
  --ui-config configs/ui-verify-prpo.yaml \
  --dry-run \
  supplierCode=100171 materialCode=MAT_DEMO purchaseOrg=2120 priceType=machine_fee
```

**看点（实测输出）：**
- 五阶段依次执行：`阶段0 寻源 → 阶段1 PRPO → 阶段2 PO就绪闸 → 阶段3 ASN → 阶段4 UI验收`
- `erpNo` 贯通到阶段3 ASN 场景（`asnScene: 高通创建ASN_1行`，sceneId=369）
- 生成 HTML 证据包：`evidence/runs/{run_id}/report.html`

**演示动作：** 跑完命令 → 打开 `report.html` → 展示"截图识别 → 参数收口 → 五阶段执行 → 证据留痕"全过程。

---

## 演示二：真实 PRPO 造单（出真单号）

**用途：** 证明这不是空跑 —— 阶段1 真能在测试环境建出 PR/PO/ERP 单号。

> ⚠️ **仅测试环境。** 需先配好 `.env`（`MIFY_ENDPOINT` / `MIFY_HTTP_TOKEN` / `SCM_BASE_URL` 等），用真实可用的供应商编码 + 物料。去掉 `--dry-run` 即为真实执行。

```bash
python tools/closed_loop_runner.py \
  --text "帮我造一条生态链 ZNB PRPO" \
  --config configs/znb-prpo.yaml \
  --ui-config configs/ui-verify-prpo.yaml \
  orderType=ZNB purchaseOrg=2120 stockOrg=MI_IOT \
  supplierCode=<真实供应商编码> \
  materials='{"materialCode1":"<真实物料编码>"}'
```

**看点：** 结果卡包含 `prNo` + `poNo` + `erpNo`（ERP 号形如 4500…）。
**完整链路：** PR创建 → PR审批 → 查合同 → PR转PO → PO审批 → 查ERP单号。**不允许只建 PR 就停。**

**命令式单跑阶段1（不走闭环）：**

```bash
python engine.py configs/znb-prpo.yaml \
  --stockOrg MI_IOT --purchaseOrg 2120 \
  --supplierCode <真实供应商编码> \
  --materials '{"materialCode1":"<真实物料编码>"}'
```

> 注：ZNB 不传 `--shipLocCode`（模板不用）。ZSC/ZYZ/ZDO 才需要。

---

## 演示三：截图造单（A 路径 —— 多模态）

**用途：** 演示"发一张 SCM/PR 截图 → 自动提取物料/供应商/组织 → 造单"。

**架构（关键，演示时要讲清）：**

```text
飞书/OpenClaw 上传截图
  → 平台 mimo-omni 视觉模型读图，按 prompts/screenshot-to-params.md 输出 JSON
  → tools/screenshot_params_adapter.py 收口（组织映射 / 多物料归一 / 缺失判定 / nextAction 分流）
  → tools/closed_loop_runner.py --screenshot-json xxx.json 合并参数 → 造数
```

> **边界（诚实声明）：** 真正"看图"的视觉模型由 **Mico / 飞书 / OpenClaw 平台的 mimo-omni** 承担，**不在本仓库代码里**。
> 因此截图造单**必须在 Mico 平台环境内演示**；脱离平台单独跑本仓库代码，它不会自己识别图片。

### 3a. 平台内演示（推荐）

在 Mico / 飞书里对已 assign 的 agent 直接发一张 SCM/PR 截图 + 一句"帮我按这张截图造数"，走完整多模态链路。

### 3b. 本地验证参数收口链（不读图，验证消费端）

模拟平台视觉模型的 JSON 输出，验证 adapter → 造数参数这一端是通的：

```bash
# 1) 造一个模拟平台视觉输出的 JSON（正常由 mimo-omni 产出）
cat > shot.json <<'JSON'
{
  "sceneType": "ZNB",
  "purchaseOrgCN": "生态链",
  "supplierCode": "108062",
  "supplierName": "威海弘霖电子",
  "materials": [
    {"materialCode": "MAT001", "materialName": "电阻", "quantity": "2"},
    {"materialCode": "MAT002", "materialName": "电容", "quantity": "5"}
  ],
  "nextAction": "RUN_DATAMAKE"
}
JSON

# 2) 跑 adapter 收口
python tools/screenshot_params_adapter.py --input shot.json --output adapted.json
```

**实测收口结果：**
- `生态链` → 自动映射 `stockOrg=MI_IOT / purchaseOrg=2120`
- 双物料归一为 `materialCode1=MAT001 / materialCode2=MAT002`
- `canProceedToDatamake=true`，`nextAction=RUN_DATAMAKE`，`missingFields=[]`

**接入闭环（把识别 JSON 喂给造数）：**

```bash
python tools/closed_loop_runner.py \
  --config configs/znb-prpo.yaml \
  --ui-config configs/ui-verify-prpo.yaml \
  --screenshot-json adapted.json \
  --text "根据飞书上传的 SCM 截图自动造数" \
  --dry-run
```

---

## 附：五种执行模式速查

| 模式 | 触发话术 | 命令要点 |
|---|---|---|
| 向导执行 | "一步步来" / "逐步执行" | 默认模式，逐阶段确认 |
| 静默执行 | "直接跑" / "静默" | 一键跑完，只出结果卡 |
| 闭环执行 | "造完做页面验收" | 带 `--ui-config` + 证据包 |
| 全链路执行 | "全链路" / "从寻源到发货通知" | 带 `--pre-clean-config` + `--asn-config` |
| 已有PO建ASN | "基于这个PO建ASN" | `--asn-mode existing-po`，跳过阶段0/1 |

---

## 附：演示排障

| 现象 | 原因 | 处理 |
|---|---|---|
| 截图发了但没识别 | 脱离了平台 / mimo-omni 未接 | 截图造单只能在 Mico 平台内跑（见演示三边界） |
| ASN 真实建单报 `BubbleException` | SAP PI 中间件后端错误 | 非代码问题，需 SAP/PI 侧查通道配置；演示时如实说明 |
| 待接入方法被拒绝 | `getPRPOPULLNoUser` 等尚未上线 | 设计如此，不谎报；换已上线方法 |
| 控制台中文乱码 | Windows GBK 控制台 | 设 `PYTHONIOENCODING=utf-8` |

---

*本手册命令均经 dry-run 实测。真实建单状态见文首"演示前速览"表，未经证实的环节已如实标注。*
