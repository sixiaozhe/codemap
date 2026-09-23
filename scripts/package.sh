#!/bin/sh
# 打包成可离线安装的工具包: dist/codemap-toolkit-<版本>.tar.gz
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
VER="${1:-dev}"
OUT="$ROOT/dist"
rm -rf "$OUT"; mkdir -p "$OUT/codemap"
cp -r "$ROOT/bin" "$ROOT/share" "$ROOT/skill" \
      "$ROOT/install.sh" "$ROOT/uninstall.sh" "$ROOT/README.md" "$ROOT/LICENSE" \
      "$OUT/codemap/"
( cd "$OUT" && tar czf "codemap-toolkit-$VER.tar.gz" codemap )
echo "$OUT/codemap-toolkit-$VER.tar.gz"
