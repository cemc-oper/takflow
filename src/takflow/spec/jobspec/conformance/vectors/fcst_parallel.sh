#!/bin/bash
#ORVIX job-name=mcv_fcst
#ORVIX nodes=24
#ORVIX ntasks-per-node=64
#ORVIX time=00:30:00
#ORVIX queue=normal
#ORVIX project=op_mcv
#ORVIX application=mcv
#ORVIX memory=25G
#ORVIX requeue=false

echo "running ${0##*/}"
