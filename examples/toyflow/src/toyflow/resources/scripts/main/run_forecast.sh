#! /usr/bin/env bash
# 写出带预报时长的示例产品，供检验和绘图任务引用。

echo "BEGIN: forecast"
echo "FORECAST_LENGTH=${FORECAST_LENGTH}"
mkdir -p "${RUN_BASE_DIR}/output"
echo "toy forecast result (+${FORECAST_LENGTH}h)" > "${RUN_BASE_DIR}/output/fcst.grb2"
echo "END: forecast"
