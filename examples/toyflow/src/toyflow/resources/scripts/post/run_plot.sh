#! /usr/bin/env bash
# 根据示例预报路径写出绘图占位产品。

echo "BEGIN: plot"
mkdir -p "${RUN_BASE_DIR}/products"
echo "toy plot of ${RUN_BASE_DIR}/output/fcst.grb2" > "${RUN_BASE_DIR}/products/fcst.png"
echo "END: plot"
