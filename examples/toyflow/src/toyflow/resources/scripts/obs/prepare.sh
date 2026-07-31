#! /usr/bin/env bash
# 观测预处理（示例）：真实系统中这里会做观测资料解码、质量控制和同化前处理。

echo "BEGIN: prepare obs"
echo "RUN_BASE_DIR=${RUN_BASE_DIR}"
mkdir -p "${RUN_BASE_DIR}/obs"
echo "toy observation data" > "${RUN_BASE_DIR}/obs/obs.dat"
echo "END: prepare obs"
