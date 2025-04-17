#!/bin/bash

if [[ "$1" == "--fix" ]]; then
  LINE_LENGTH=$(cat tox.ini | grep 'max-line-length' | cut -d'=' -f2 | awk '{ print $1 }')
  black -l ${LINE_LENGTH:-132} src/stack/ 
fi

flake8 --config tox.ini
