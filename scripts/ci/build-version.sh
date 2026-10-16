#!/usr/bin/env bash
# Prints the version and branch for this build as KEY=value lines, for
# "$GITHUB_ENV" (or `eval`):
#   tag vX.Y.Z      BUILD_VERSION=X.Y.Z               BUILD_BRANCH=main
#   anything else   BUILD_VERSION=X.Y.(Z+1).ci.<run>  BUILD_BRANCH=<branch>
# where vX.Y.Z is the latest release tag (v0.0.0 if none) and <run> is the
# GitHub Actions run number. Needs the tags: actions/checkout fetch-depth: 0.

set -euo pipefail

ref_type="${GITHUB_REF_TYPE:-}"
ref_name="${GITHUB_REF_NAME:-}"

if [[ "$ref_type" == "tag" && "$ref_name" =~ ^v([0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
  echo "BUILD_VERSION=${BASH_REMATCH[1]}"
  echo "BUILD_BRANCH=main"
  exit 0
fi

latest="$(git describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*' 2>/dev/null || echo v0.0.0)"
if [[ ! "$latest" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
  latest=v0.0.0
  [[ "$latest" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]
fi
next="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}.$((BASH_REMATCH[3] + 1))"

# Pull requests build the source branch
branch="${GITHUB_HEAD_REF:-${ref_name:-$(git rev-parse --abbrev-ref HEAD)}}"

echo "BUILD_VERSION=${next}.ci.${GITHUB_RUN_NUMBER:-0}"
echo "BUILD_BRANCH=${branch}"
