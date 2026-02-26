# Builds the shiv "package" for distribution
mkdir -p ./package
version_string=$( ./scripts/create_build_tag_file.sh )
uvx shiv -c stack -o package/stack-${version_string} .
