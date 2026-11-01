#!/usr/bin/env bash
set -euo pipefail

version=1.9.2
curl -fsSL "https://example.com/releases/tool-${version}.tar.gz" -o tool.tgz
tar -xzf tool.tgz
