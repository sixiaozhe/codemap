#!/bin/sh
# codemap 工具包安装脚本 (完全离线, 无需 root)
#
# 用法: ./install.sh [安装前缀]
#   默认前缀: $HOME/.local
#   例:  ./install.sh                 # 装到 ~/.local
#        ./install.sh /opt/codemap   # 装到 /opt/codemap (需写权限)
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
PREFIX="${1:-$HOME/.local}"
BINDIR="$PREFIX/bin"
LIBDIR="$PREFIX/share/codemap"

echo "== codemap 工具包安装 =="
echo "安装前缀: $PREFIX"

# 1) 检查 python3 >= 3.6
if ! command -v python3 >/dev/null 2>&1; then
    echo "错误: 未找到 python3, 请先安装 Python 3.6 或更高版本" >&2
    exit 1
fi
PYV=$(python3 -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')
if ! python3 -c 'import sys;sys.exit(0 if sys.version_info[:2]>=(3,6) else 1)' 2>/dev/null; then
    echo "错误: python3 版本为 $PYV, 需要 >= 3.6" >&2
    exit 1
fi
echo "python3: $PYV"

# 2) 架构提示
ARCH=$(uname -m)
echo "架构: $ARCH"
if [ "$ARCH" != "x86_64" ]; then
    echo "警告: 内置 cscope 是 x86_64 静态二进制, 当前架构可能无法运行" >&2
fi

# 3) 复制文件
mkdir -p "$BINDIR" "$LIBDIR"
cp "$HERE/bin/cscope"      "$BINDIR/cscope"
cp "$HERE/bin/lizard.pyz"  "$BINDIR/lizard.pyz"
cp "$HERE/bin/codemap"     "$BINDIR/codemap"
cp "$HERE/share/codemap/analyze.py"    "$LIBDIR/analyze.py"
cp "$HERE/share/codemap/build_html.py" "$LIBDIR/build_html.py"
cp "$HERE/share/codemap/template.html" "$LIBDIR/template.html"
cp "$HERE/share/codemap/ai_export.py"  "$LIBDIR/ai_export.py"
cp "$HERE/share/codemap/query.py"      "$LIBDIR/query.py"
cp "$HERE/share/codemap/mcp_server.py" "$LIBDIR/mcp_server.py"
chmod +x "$BINDIR/cscope" "$BINDIR/lizard.pyz" "$BINDIR/codemap"

# 4) 自检
echo "自检:"
printf '  cscope: '; "$BINDIR/cscope" --version 2>&1 | head -1
printf '  lizard: '; python3 "$BINDIR/lizard.pyz" --version 2>&1 | head -1
printf '  codemap: '; [ -x "$BINDIR/codemap" ] && echo "OK" || echo "缺失"

# 5) PATH 提示
case ":$PATH:" in
    *":$BINDIR:"*) ;;
    *)
        echo
        echo "提示: 把 $BINDIR 加入 PATH 后可在任意目录使用 codemap:"
        echo "    echo 'export PATH=\"$BINDIR:\$PATH\"' >> ~/.bashrc && . ~/.bashrc"
        ;;
esac
echo
echo "安装完成。用法: codemap <项目目录> [排除模式]"
echo "示例: codemap ./src      # 生成 ./codemap.html"
