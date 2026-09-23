#!/bin/sh
# codemap 工具包卸载脚本
# 用法: ./uninstall.sh [安装前缀]   (默认 $HOME/.local)
set -e
PREFIX="${1:-$HOME/.local}"
BINDIR="$PREFIX/bin"
LIBDIR="$PREFIX/share/codemap"

rm -f "$BINDIR/cscope" "$BINDIR/lizard.pyz" "$BINDIR/codemap"
rm -f "$LIBDIR/analyze.py" "$LIBDIR/build_html.py" "$LIBDIR/template.html" "$LIBDIR/ai_export.py" "$LIBDIR/query.py" "$LIBDIR/mcp_server.py"
rmdir "$LIBDIR" 2>/dev/null || true
echo "已卸载 (前缀: $PREFIX)"
