#! /usr/bin/env bash
# 将示例观测写到本次运行目录。

echo "BEGIN: prepare obs"
echo "RUN_BASE_DIR=${RUN_BASE_DIR}"
mkdir -p "${RUN_BASE_DIR}/obs"
echo "toy observation data" > "${RUN_BASE_DIR}/obs/obs.dat"
echo "END: prepare obs"
