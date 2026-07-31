#! /usr/bin/env bash
# 预报（示例）：真实系统中这里会调用模式主程序（并行）。

echo "BEGIN: forecast"
echo "FORECAST_LENGTH=${FORECAST_LENGTH}"
mkdir -p "${RUN_BASE_DIR}/output"
echo "toy forecast result (+${FORECAST_LENGTH}h)" > "${RUN_BASE_DIR}/output/fcst.grb2"
echo "END: forecast"
