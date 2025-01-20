#!/usr/bin/env bash
# Usage: publish_shiv_package_github.sh <major> <minor> <patch>
# Uses this script package to publish a new release:
# https://github.com/cerc-io/github-release-api
# User must define: BPI_GH_RELEASE_SCRIPTS_DIR
# pointing to the location of that cloned repository
# e.g. 
# cd ~/projects
# git clone https://github.com/cerc-io/github-release-api
# cd ./stack
# export BPI_GH_RELEASE_SCRIPTS_DIR=~/projects/github-release-api
# ./scripts/publish_shiv_package_github.sh
# In addition, a valid GitHub token must be defined in
# BPI_PACKAGE_RELEASE_GITHUB_TOKEN
if [[ -z "${BPI_PACKAGE_RELEASE_GITHUB_TOKEN}" ]]; then
    echo "BPI_PACKAGE_RELEASE_GITHUB_TOKEN is not set" >&2
    exit 1
fi
# TODO: check args and env vars
major=$1
minor=$2
patch=$3
export PATH=$BPI_GH_RELEASE_SCRIPTS_DIR:$PATH
github_org="cerc-io"
github_repository="stack"
latest_package=$(ls -1t ./package/* | head -1)
uploaded_package="./package/bpi-so"
# Remove any old package
rm ${uploaded_package}
cp ${latest_package} ${uploaded_package}
github_release_manager.sh \
        -l notused -t ${BPI_PACKAGE_RELEASE_GITHUB_TOKEN} \
        -o ${github_org} -r ${github_repository} \
        -d v${major}.${minor}.${patch} \
        -c create -m "Release v${major}.${minor}.${patch}"
github_release_manager.sh \
        -l notused -t ${BPI_PACKAGE_RELEASE_GITHUB_TOKEN} \
        -o ${github_org} -r ${github_repository} \
        -d v${major}.${minor}.${patch} \
        -c upload ${uploaded_package}
