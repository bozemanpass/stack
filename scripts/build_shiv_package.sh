# Builds the shiv "package" for distribution
mkdir -p ./package
version_string=$( ./scripts/create_build_tag_file.sh )
shiv -c bpi-so -o package/bpi-so-${version_string} .
