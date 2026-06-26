# AI 数据智造多模态闭环引擎 - 后续待办

## 明日优先级

1. **真实 UI 验收联调**
   - 安装依赖：`pip install playwright`、`python -m playwright install chromium`
   - 配置真实 `SCM_BASE_URL`
   - 按 SRM 页面补齐 `configs/ui-verify-prpo.yaml` 的搜索框、按钮、结果断言选择器
   - 跑通一次非 `--dry-run` 的 `tools/closed_loop_runner.py`

2. **截图/SOP 真多模态识别**
   - 评估接入 Mify 视觉工作流或 OCR
   - 将 `tools/vision_extract.py` 从规则提取升级为“截图 → 字段候选 → 缺失字段追问”
   - 保留识别失败降级策略：失败时只追问，不直接执行

3. ~~**主数据清洗补齐**~~ ✅
   - ~~明确主数据清洗输入、输出和失败边界~~ → `srm_price_clean.py` 加输入校验 + 结果断言
   - ~~补齐主数据清洗 YAML/脚本入口~~ → `srm-price-clean.yaml` 加回查步骤（verify_asl / verify_price_list / verify_machine_fee）
   - ~~在闭环里放到 PRPO 造数前置步骤~~ → `closed_loop_runner.py` 失败时记录具体错误，不再默默 pass

4. **参赛提交包**
   - 用脱敏数据跑一次完整演示
   - 检查 `python scripts/validate_skill.py`
   - 准备 3 分钟视频分镜：截图触发 → 参数确认 → 造数 → UI 验收 → 证据包
   - 更新 V8 文章和一页纸说明里的最终截图与指标

## 当前边界

- 已实现：PRPO 造数主线、多模态闭环外层、UI 验收框架、失败诊断、HTML 证据包、敏感原始导出清理。
- 未实现：ASN，不写入已完成能力，只作为未来规划。
- 注意：真实凭证、内部 URL、真实供应商/物料/项目号不得进入 GitHub 或参赛材料。

