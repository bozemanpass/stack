#!/usr/bin/env bash
# Beginnings of a script to quickly spin up and test a deployment
if [[ -n "$BPI_SCRIPT_DEBUG" ]]; then
    set -x
fi
if [[ -n "$1" ]]; then
	stack_name=$1
else
	stack_name="test"
fi
spec_file_name="${stack_name}-spec.yml"
deployment_dir_name="${stack_name}-deployment"
rm -f ${spec_file_name}
rm -rf ${deployment_dir_name}
bpi-so --stack ${stack_name} deploy --deploy-to compose init --output ${spec_file_name}
bpi-so --stack ${stack_name} deploy --deploy-to compose create --deployment-dir ${deployment_dir_name} --spec-file ${spec_file_name}
#bpi-so deployment --dir ${deployment_dir_name} start
#bpi-so deployment --dir ${deployment_dir_name} ps
#bpi-so deployment --dir ${deployment_dir_name} stop
