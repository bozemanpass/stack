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
stack --stack ${stack_name} deploy --deploy-to compose init --output ${spec_file_name}
stack --stack ${stack_name} deploy --deploy-to compose create --deployment-dir ${deployment_dir_name} --spec-file ${spec_file_name}
#stack deployment --dir ${deployment_dir_name} start
#stack deployment --dir ${deployment_dir_name} ps
#stack deployment --dir ${deployment_dir_name} stop
