#! /usr/bin/env bash
# 后处理绘图（示例）：真实系统中这里会做 GRIB2 后处理和产品绘制。

echo "BEGIN: plot"
mkdir -p "${RUN_BASE_DIR}/products"
echo "toy plot of ${RUN_BASE_DIR}/output/fcst.grb2" > "${RUN_BASE_DIR}/products/fcst.png"
echo "END: plot"
