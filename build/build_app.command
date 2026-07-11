#!/bin/bash
# ============================================================
# 聚慧 PolySage 一键构建脚本
# 双击此文件即可构建 .app 和 .dmg 到 build/ 目录
# ============================================================

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 路径
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$PROJECT_DIR/app"
BUILD_DIR="$SCRIPT_DIR"

echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}  聚慧 PolySage 构建工具${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# 检查 app 目录
if [ ! -d "$APP_DIR" ]; then
    echo -e "${RED}❌ 找不到 app/ 目录: $APP_DIR${NC}"
    echo -e "${BLUE}请确保 build_app.command 与 app/ 在同一项目根目录下${NC}"
    read -p "按回车键退出..."
    exit 1
fi

# 检查 Python 3.10
PY310=""
if [ -d "/Users/damon/Library/Application Support/TRAE SOLO CN/ModularData/ai-agent/vm/tools/opt/python@3.10/3.10.20_3" ]; then
    PY310="/Users/damon/Library/Application Support/TRAE SOLO CN/ModularData/ai-agent/vm/tools/opt/python@3.10/3.10.20_3"
elif command -v python3.10 &> /dev/null; then
    PY310=$(dirname $(dirname $(which python3.10)))
elif command -v python3 &> /dev/null; then
    PY310=$(dirname $(dirname $(which python3)))
else
    echo -e "${RED}❌ 未找到 Python 3，请先安装 Python 3.10+${NC}"
    read -p "按回车键退出..."
    exit 1
fi

echo -e "${YELLOW}Python 路径: $PY310${NC}"
echo ""

# 设置 Python 环境
export PYTHONHOME="$PY310/Frameworks/Python.framework/Versions/3.10" 2>/dev/null || true
export PATH="$PY310/libexec/bin:$PY310/bin:$PATH"
unset PYTHONPATH

# 构建版本号
VERSION="v1.0.0"
echo -e "${YELLOW}构建版本: $VERSION${NC}"
echo ""

# 清理 build/ 目录中的旧产物
echo -e "${YELLOW}[1/3] 清理旧产物...${NC}"
rm -rf "$BUILD_DIR/聚慧.app" "$BUILD_DIR/聚慧-${VERSION}-arm64.dmg"
echo -e "${GREEN}  ✅ 旧产物已清理${NC}"
echo ""

# 运行构建脚本（build_dmg.sh 已自动输出到 build/ 目录）
echo -e "${YELLOW}[2/3] 构建 .app 和 .dmg...${NC}"
cd "$APP_DIR"
GITHUB_ACTIONS=true bash build_dmg.sh 2>&1 | tail -20

# 检查构建结果
if [ ! -f "$BUILD_DIR/聚慧-${VERSION}-arm64.dmg" ]; then
    echo -e "${RED}❌ 构建失败：未找到 $BUILD_DIR/聚慧-${VERSION}-arm64.dmg${NC}"
    read -p "按回车键退出..."
    exit 1
fi

echo ""
echo -e "${YELLOW}[3/3] 验证产物...${NC}"
echo -e "${GREEN}📦 产物位置：${NC}"
ls -lh "$BUILD_DIR/聚慧.app" "$BUILD_DIR/聚慧-${VERSION}-arm64.dmg" 2>/dev/null | awk '{print "  " $NF " (" $5 ")"}'
echo ""

echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}  🎉 构建完成！${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""
echo -e "${BLUE}💡 如需 Windows .exe，请从 GitHub Release 下载：${NC}"
echo -e "${BLUE}  https://github.com/a122065560/PolySage/releases${NC}"
echo ""

# 询问是否下载 Windows exe
if command -v gh &> /dev/null && gh auth status &> /dev/null 2>&1; then
    read -p "是否下载 Windows .exe？(y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}  下载 聚慧-${VERSION}-Windows.exe...${NC}"
        gh release download "$VERSION" --pattern "聚慧-${VERSION}-Windows.exe" --dir "$BUILD_DIR" --clobber 2>&1
        echo -e "${GREEN}  ✅ 聚慧-${VERSION}-Windows.exe → build/${NC}"
    fi
fi

echo ""
read -p "按回车键退出..."
