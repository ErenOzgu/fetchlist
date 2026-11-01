#!/usr/bin/env bash
# Regenerates the committed outputs in examples/ from examples/sample, or checks that they are what the tool prints now.
#   examples/generate.sh           write
#   examples/generate.sh --check   fail if a committed file differs (CI does this, so the README cannot drift)
set -euo pipefail
cd "$(dirname "$0")/.."

mode=${1:-write}
tmp=$(mktemp -d)
trap 'rm -rf "${tmp}"' EXIT

python -m fetchlist scan examples/sample > "${tmp}/sample.scan.txt"
python -m fetchlist check examples/sample > "${tmp}/sample.check.txt" || [ $? -eq 1 ]
python -m fetchlist mirror examples/sample --what hosts > "${tmp}/sample.mirror.txt" 2> /dev/null

status=0
for name in sample.scan.txt sample.check.txt sample.mirror.txt; do
  if [ "${mode}" = "--check" ]; then
    diff -u "examples/${name}" "${tmp}/${name}" || status=1
  else
    cp "${tmp}/${name}" "examples/${name}"
  fi
done
exit "${status}"
