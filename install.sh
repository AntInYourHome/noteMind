#!/usr/bin/env bash
# NoteMind 一键安装脚本
# 用法：./install.sh
#
# 注意：NoteMind 核心功能零外部依赖，只需 Python 3.10+
# 此脚本仅用于可选格式解析依赖的安装

set -e

echo "=== NoteMind 安装检查 ==="

# 检查 Python
if ! command -v python3 &>/dev/null; then
    echo "错误：未找到 python3，请先安装 Python 3.10+"
    exit 1
fi

PYTHON_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python 版本：$PYTHON_VER"

# 检查可选依赖安装选项
echo ""
echo "选择要安装的可选依赖（输入数字，空格分隔，0=全部跳过）："
echo "  1) PDF 解析 (pymupdf)"
echo "  2) Word 解析 (python-docx)"
echo "  3) PPT 解析 (python-pptx)"
echo "  4) Excel 解析 (openpyxl)"
echo "  5) Markdown 清洗 (mistune)"
echo "  6) OneNote 解析 (onenote2xml)"
echo "  0) 全部跳过（仅使用核心功能）"
read -p "> " choices

# 映射选择
declare -A PKGS
PKGS[1]="pymupdf"
PKGS[2]="python-docx"
PKGS[3]="python-pptx"
PKGS[4]="openpyxl"
PKGS[5]="mistune"
PKGS[6]="onenote2xml lxml"

if echo "$choices" | grep -q "0"; then
    echo "跳过可选依赖安装"
else
    for c in $choices; do
        if [ -n "${PKGS[$c]}" ]; then
            echo "安装: ${PKGS[$c]}"
            pip install ${PKGS[$c]} -q 2>/dev/null || pip3 install ${PKGS[$c]} -q 2>/dev/null
        fi
    done
fi

# 创建默认 Vault 目录
VAULT_PATH="${HOME}/knowledge-base"
if [ ! -d "$VAULT_PATH" ]; then
    echo "创建默认 Vault 目录: $VAULT_PATH"
    mkdir -p "$VAULT_PATH"/{芯片,安全,项目,笔记,其他,_archive,_failed}
fi

echo ""
echo "=== 安装完成 ==="
echo ""
echo "1. 编辑 config.json 修改 API key 和分类"
echo "2. 运行导入：./import.py --source /path/to/files"
echo ""
echo "用法："
echo "  ./import.py --source ./my_files"
echo "  ./import.py --source ./my_files --vault ~/my-vault"
echo "  ./import.py --source ./my_files --dry-run     # 预览模式"
echo "  ./import.py --source ./my_files --resume      # 从断点恢复"
