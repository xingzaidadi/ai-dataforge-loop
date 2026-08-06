# tests/

DataForge Loop 的单元测试。**纯 `assert` 风格，不依赖 `pytest`**——但同时也能被 `pytest` 直接收集，两种运行方式都支持。

## 两种运行方式

**方式一：pytest（推荐，可批量 + 报告）**

```bash
python -m pytest tests/ -q
```

**方式二：直接执行单个文件（无需装 pytest）**

每个测试文件底部都有 `if __name__ == "__main__":` 入口，逐个调用测试函数并打印通过信息：

```bash
python tests/test_condition_contains.py
python tests/test_srm_asn_create.py
```

## 现有测试

| 文件 | 覆盖 |
|---|---|
| `test_condition_contains.py` | `lib/flow.py` 的 `contains` 算子：正向/反向匹配、`None` 左值安全、动态右值 `{{ }}` 引用、以及 `check_price_type` → `create_machine_fee` / `check_asl` 的实际分支路由 |
| `test_srm_asn_create.py` | `srm_asn_create.py` 的 `resolve_category`（三大 EDI 供应商编码 / 大货 pullCommand / 成品 ZWW+料号 / 寄存 ZJC / 兜底 PO）与 `resolve_scene`（类别×行数→场景 ID 映射） |

## 约定

- 测试不 mock 真实 mify 客户端：涉及引擎的用例用 `FlowEngine(config=..., inputs=..., mify=None)` 直接构造，只验证纯逻辑（条件求值、类别/场景解析），不触发 HTTP/SQL。
- 文件顶部有 UTF-8 stdout/stderr reconfigure 守卫，避免 Windows GBK 控制台在打印 emoji（✅/⚠️/⛔）时抛 `UnicodeEncodeError`。
