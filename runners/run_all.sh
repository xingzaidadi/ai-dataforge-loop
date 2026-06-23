#!/bin/bash
# 并行跑所有 PRPO 场景并统计时间
# 用法: bash runners/run_all.sh
set -o pipefail
cd "$(dirname "$0")/.."

run_scenario() {
    local name="$1"
    shift
    local start=$(date +%s)
    echo "[$name] 开始..."
    local output
    if output=$(python3 engine.py "$@" 2>&1); then
        local end=$(date +%s)
        local elapsed=$((end - start))
        local pr=$(echo "$output" | grep -oP 'PR号: \K[0-9]+' | tail -1)
        local po=$(echo "$output" | grep -oP 'PO号: \K[0-9]+' | tail -1)
        local erp=$(echo "$output" | grep -oP 'ERP单号: \K[0-9]+' | tail -1)
        echo "[OK] [$name] 耗时 ${elapsed}s | PR=${pr:-N/A} | PO=${po:-N/A} | ERP=${erp:-N/A}"
    else
        local end=$(date +%s)
        local elapsed=$((end - start))
        echo "[FAIL] [$name] 耗时 ${elapsed}s"
    fi
    echo "$output" > "/tmp/run_all_${name}.log"
}

echo "开始全场景测试 $(date '+%H:%M:%S')"
echo "================================================"

run_scenario "ZNB" configs/znb-prpo.yaml \
    --stockOrg MI_IOT --purchaseOrg 2120 \
    --supplierCode 108062 \
    --materials '{"materialCode1": "1710301000006A"}' \
    --projectCode "EcoOdmJdm20240708220947-EU" --shipLocCode 129797 &

run_scenario "ZWW-成品" configs/zww-prpo.yaml \
    --stockOrg MI_TV --purchaseOrg 1111 \
    --supplierCode 109773 \
    --sku ELA4130CN --prodMaterialCode D65055000009P \
    --projectCode "TV1111" --goodsId 15563 &

run_scenario "ZSC" configs/zsc-prpo.yaml \
    --stockOrg MI_PHONE --purchaseOrg 1110 \
    --supplierCode 101131 \
    --materials '{"materialCode1": "22BM1CC226AD"}' \
    --projectCode "L18-CN" --shipLocCode P3882 &

run_scenario "ZYZ" configs/zyz-prpo.yaml \
    --stockOrg MI_NOTEBOOK --purchaseOrg 111K \
    --supplierCode 100339 \
    --materials '{"materialCode1": "1320601000014A"}' \
    --projectCode "M59-CN" --shipLocCode 127862 &

run_scenario "ZWW-半成品" configs/zww-semi-prpo.yaml \
    --stockOrg MI_TV --purchaseOrg 1111 \
    --supplierCode 133490 \
    --materials '{"materialCode1": "D430240000006"}' \
    --projectCode "MN110GL455" --shipLocCode 143307 &

wait

echo ""
echo "================================================"
echo "全部完成 $(date '+%H:%M:%S')"
