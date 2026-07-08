#!/bin/bash
# ============================================================
# PolySage（聚慧）本地一键发布脚本
# ------------------------------------------------------------
# 用法: ./publish.sh <版本号>
# 示例: ./publish.sh v1.0.0
#
# 流程:
#   1. 创建 Git 标签
#   2. 推送标签触发 GitHub Actions
#   3. 监听 CI 构建进度
#   4. 下载构建产物到 ./dist/
#
# 产物:
#   ./dist/PolySage-{版本号}-macOS.dmg
#   ./dist/PolySage-{版本号}-Windows.exe
#
# 前置条件:
#   - 已安装 GitHub CLI (gh) 并完成认证
#   - 当前分支已推送到远程仓库
# ============================================================
set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ----------------------------------------------------------------
# 参数检查
# ----------------------------------------------------------------
VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    echo -e "${RED}错误: 请提供版本号${NC}"
    echo -e "  用法: $0 <版本号>"
    echo -e "  示例: $0 v1.0.0"
    exit 1
fi

# 产物目录
DIST_DIR="./dist"
mkdir -p "$DIST_DIR"

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  聚慧 PolySage 发布脚本${NC}"
echo -e "${BLUE}  版本号: ${VERSION}${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# ----------------------------------------------------------------
# Step 1: 创建 Git 标签
# ----------------------------------------------------------------
echo -e "${YELLOW}[1/5] 创建 Git 标签 ${VERSION} ...${NC}"
if git rev-parse "$VERSION" >/dev/null 2>&1; then
    echo -e "${YELLOW}  标签 ${VERSION} 已存在，跳过创建${NC}"
else
    git tag "$VERSION"
    echo -e "${GREEN}  标签 ${VERSION} 创建成功${NC}"
fi
echo ""

# ----------------------------------------------------------------
# Step 2: 推送标签到远程仓库（触发 GitHub Actions）
# ----------------------------------------------------------------
echo -e "${YELLOW}[2/5] 推送标签到远程仓库 ...${NC}"
git push origin "$VERSION"
echo -e "${GREEN}  标签推送成功，GitHub Actions 已触发${NC}"
echo ""

# ----------------------------------------------------------------
# Step 3: 监听 GitHub Actions 运行
# ----------------------------------------------------------------
echo -e "${YELLOW}[3/5] 监听 GitHub Actions 运行 ...${NC}"
# 等待 workflow 触发后获取最新 run
sleep 5
RUN_ID=$(gh run list --workflow=release.yml --limit=1 --json databaseId --jq '.[0].databaseId')
if [ -z "$RUN_ID" ]; then
    echo -e "${RED}  未找到对应的 workflow 运行，请检查 GitHub Actions 配置${NC}"
    exit 1
fi
echo -e "${BLUE}  Run ID: ${RUN_ID}${NC}"
echo -e "${BLUE}  实时监听构建进度（通常需要 10-20 分钟）...${NC}"
# 实时监听，构建失败时退出码非零
gh run watch "$RUN_ID" --exit-status
echo -e "${GREEN}  构建完成${NC}"
echo ""

# ----------------------------------------------------------------
# Step 4: 下载构建产物
# ----------------------------------------------------------------
echo -e "${YELLOW}[4/5] 下载构建产物 ...${NC}"
# 下载到临时目录（gh run download 会为每个 artifact 创建子目录）
TMP_DIR=$(mktemp -d)
gh run download "$RUN_ID" --dir "$TMP_DIR"
echo -e "${GREEN}  产物已下载${NC}"
echo ""

# ----------------------------------------------------------------
# Step 5: 整理产物到 ./dist/
# ----------------------------------------------------------------
echo -e "${YELLOW}[5/5] 整理产物到 ${DIST_DIR}/ ...${NC}"

# macOS DMG 产物
MACOS_DMG="${DIST_DIR}/PolySage-${VERSION}-macOS.dmg"
if [ -f "$TMP_DIR/macos-dmg/PolySage-${VERSION}-macOS.dmg" ]; then
    cp "$TMP_DIR/macos-dmg/PolySage-${VERSION}-macOS.dmg" "$MACOS_DMG"
    echo -e "${GREEN}  macOS: ${MACOS_DMG}${NC}"
else
    echo -e "${RED}  未找到 macOS DMG 产物${NC}"
fi

# Windows EXE 产物
WIN_EXE="${DIST_DIR}/PolySage-${VERSION}-Windows.exe"
if [ -f "$TMP_DIR/windows-exe/PolySage-${VERSION}-Windows.exe" ]; then
    cp "$TMP_DIR/windows-exe/PolySage-${VERSION}-Windows.exe" "$WIN_EXE"
    echo -e "${GREEN}  Windows: ${WIN_EXE}${NC}"
else
    echo -e "${RED}  未找到 Windows EXE 产物${NC}"
fi

# 清理临时目录
rm -rf "$TMP_DIR"

echo ""
echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}  发布完成！${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""
echo -e "${GREEN}产物文件：${NC}"
ls -lh "$DIST_DIR"/PolySage-${VERSION}-* 2>/dev/null || true
echo ""
echo -e "${BLUE}后续步骤：${NC}"
echo -e "  1. 在 GitHub Releases 页面查看发布内容"
echo -e "  2. 分发安装包给用户"
