#!/bin/bash
# ============================================================
# PolySage 一键打包脚本
# 生成 macOS ARM64 .app 和 .dmg 安装包
# ============================================================
set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  🪑 聚慧 PolySage 打包脚本 (ARM64)${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# 变量
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

DIST_DIR="$SCRIPT_DIR/dist"
BUILD_DIR="$SCRIPT_DIR/build"
DMG_NAME="${DMG_NAME:-PolySage-1.0.0-arm64.dmg}"

# ----------------------------------------------------------------
# Step 1: 检查依赖
# ----------------------------------------------------------------
echo -e "${YELLOW}[1/7] 检查依赖...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ 未找到 python3${NC}"
    exit 1
fi

PY_ARCH=$(python3 -c "import platform; print(platform.machine())")
echo -e "${GREEN}  ✅ Python $(python3 --version | cut -d' ' -f2) ($PY_ARCH)${NC}"

# 安装项目依赖
echo -e "${YELLOW}  ⏳ 检查项目依赖...${NC}"
python3 -m pip install -r requirements.txt --break-system-packages -q 2>&1 | tail -3
echo -e "${GREEN}  ✅ 项目依赖已就绪${NC}"

# 检查 PyInstaller
if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo -e "${YELLOW}  ⏳ 安装 PyInstaller...${NC}"
    python3 -m pip install pyinstaller==6.3.0 --break-system-packages -q
fi
echo -e "${GREEN}  ✅ PyInstaller $(python3 -m PyInstaller --version)${NC}"

echo ""

# ----------------------------------------------------------------
# Step 2: 清理旧产物
# ----------------------------------------------------------------
echo -e "${YELLOW}[2/7] 清理旧产物...${NC}"
rm -rf "$BUILD_DIR" "$DIST_DIR"
rm -rf "$SCRIPT_DIR/__pycache__"
rm -f "$SCRIPT_DIR/PolySage.spec"
find "$SCRIPT_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
echo -e "${GREEN}  ✅ 已清理${NC}"
echo ""

# ----------------------------------------------------------------
# Step 3: PyInstaller 打包（排除 Qt6 framework 避免符号链接冲突）
# ----------------------------------------------------------------
echo -e "${YELLOW}[3/7] PyInstaller 打包中（ARM64）...${NC}"
echo -e "${BLUE}  这可能需要几分钟...${NC}"

export PYINSTALLER_CONFIG_DIR="${TMPDIR:-/tmp}/pyinstaller_cache"
mkdir -p "$PYINSTALLER_CONFIG_DIR"

python3 -m PyInstaller \
    --noconfirm \
    --clean \
    --target-arch arm64 \
    --windowed \
    --osx-bundle-identifier com.polysage.app \
    --name "PolySage" \
    --icon AppIcon.icns \
    --add-data "logo_ui.png:." \
    --add-data "logo_ui@2x.png:." \
    main.py \
    ui_main_window.py \
    ui_widgets.py \
    ui_worker.py \
    ui_flowlayout.py \
    browser.py \
    core.py \
    config_manager.py \
    utils.py \
    logger.py \
    --hidden-import PyQt6 \
    --hidden-import PyQt6.QtCore \
    --hidden-import PyQt6.QtGui \
    --hidden-import PyQt6.QtWidgets \
    --hidden-import PyQt6.sip \
    --hidden-import qasync \
    --hidden-import playwright \
    --hidden-import playwright.async_api \
    --hidden-import playwright._impl \
    --hidden-import openai \
    --collect-submodules PyQt6 \
    --collect-binaries PyQt6 \
    --exclude-module PyQt6.Qt6 \
    --collect-all playwright \
    --collect-data qasync \
    --copy-metadata openai \
    --copy-metadata qasync \
    --exclude-module tkinter \
    --exclude-module matplotlib \
    --exclude-module numpy \
    --exclude-module pandas \
    --exclude-module PIL \
    --exclude-module PyQt5 \
    --exclude-module PySide6 \
    2>&1 | tail -10

if [ ! -d "$DIST_DIR/PolySage.app" ]; then
    echo -e "${RED}❌ 打包失败${NC}"
    exit 1
fi
echo -e "${GREEN}  ✅ .app 打包成功${NC}"
echo ""

# ----------------------------------------------------------------
# Step 4: 复制 Qt6 framework 和 Playwright driver
# ----------------------------------------------------------------
echo -e "${YELLOW}[4/7] 嵌入 Qt6 和 Playwright driver...${NC}"

# 找到 PyQt6 的 Qt6 库路径
QT6_LIB=$(python3 -c "
import PyQt6, os
qt6_dir = os.path.join(os.path.dirname(PyQt6.__file__), 'Qt6', 'lib')
print(qt6_dir)
" 2>/dev/null)

if [ -n "$QT6_LIB" ] && [ -d "$QT6_LIB" ]; then
    mkdir -p "$DIST_DIR/PolySage/_internal/PyQt6/Qt6/lib"
    # 只复制实际使用的3个Qt6框架（而非全部85个），节省约400MB
    for fw in QtCore QtGui QtWidgets; do
        cp -R "$QT6_LIB/"*"$fw"* "$DIST_DIR/PolySage/_internal/PyQt6/Qt6/lib/" 2>/dev/null
        echo "  复制 Qt6/$fw framework"
    done
    echo -e "${GREEN}  ✅ Qt6 framework 已嵌入（仅 QtCore/QtGui/QtWidgets）${NC}"
else
    echo -e "${YELLOW}  ⚠️  Qt6 库未找到${NC}"
fi

# 找到 Playwright driver
PW_DRIVER=$(python3 -c "
import playwright, os
print(os.path.join(os.path.dirname(playwright.__file__), 'driver'))
" 2>/dev/null)

if [ -n "$PW_DRIVER" ] && [ -d "$PW_DRIVER" ]; then
    mkdir -p "$DIST_DIR/PolySage/_internal/playwright"
    cp -r "$PW_DRIVER" "$DIST_DIR/PolySage/_internal/playwright/driver"
    echo -e "${GREEN}  ✅ Playwright driver 已嵌入${NC}"
else
    echo -e "${YELLOW}  ⚠️  Playwright driver 未找到${NC}"
fi

# 同步 _internal 到 .app
rm -rf "$DIST_DIR/PolySage.app/Contents/Resources/_internal"
cp -r "$DIST_DIR/PolySage/_internal" "$DIST_DIR/PolySage.app/Contents/Resources/_internal"

# 更新 Info.plist
cp "$SCRIPT_DIR/Info.plist" "$DIST_DIR/PolySage.app/Contents/Info.plist"

# 复制应用图标
if [ -f "$SCRIPT_DIR/AppIcon.icns" ]; then
    cp "$SCRIPT_DIR/AppIcon.icns" "$DIST_DIR/PolySage.app/Contents/Resources/AppIcon.icns"
    echo -e "${GREEN}  ✅ 应用图标已嵌入${NC}"
else
    echo -e "${YELLOW}  ⚠️  AppIcon.icns 未找到${NC}"
fi

# ----------------------------------------------------------------
# 关键修复：创建 Qt6 framework 符号链接
# .so 文件依赖 @rpath/QtXxx（纯名称），需创建符号链接指向 framework
# ----------------------------------------------------------------
APP_BUNDLE="$DIST_DIR/PolySage.app"
APP_QT6LIB="$APP_BUNDLE/Contents/Resources/_internal/PyQt6/Qt6/lib"
APP_FW="$APP_BUNDLE/Contents/Frameworks"

echo -e "${BLUE}  创建 Qt6 framework 符号链接...${NC}"

# 1. 在 Qt6/lib 目录创建符号链接 (QtXxx -> QtXxx.framework/Versions/A/QtXxx)
#    供可执行文件的 rpath @executable_path/../Resources/_internal/PyQt6/Qt6/lib 使用
cd "$APP_QT6LIB"
symlink_count=0
for fw_dir in *.framework; do
    fw_name="${fw_dir%.framework}"
    if [ -f "$fw_dir/Versions/A/$fw_name" ]; then
        ln -sf "$fw_dir/Versions/A/$fw_name" "$fw_name"
        symlink_count=$((symlink_count + 1))
    fi
done
echo -e "${GREEN}  ✅ Qt6/lib 目录创建 $symlink_count 个符号链接${NC}"

# 2. 在 Frameworks/ 目录创建符号链接 (QtXxx -> ../Resources/_internal/PyQt6/Qt6/lib/QtXxx.framework/Versions/A/QtXxx)
#    供 .so 文件的 rpath @loader_path/.. 使用
#    注意：相对路径是 ../Resources/（一层 ..），不是 ../../Resources/（两层 ..）
cd "$APP_FW"
# 先清理可能存在的旧符号链接
for f in Qt*; do
    [ -L "$f" ] && rm "$f"
done
# 创建正确的符号链接
fw_count=0
for fw_dir in "$APP_QT6LIB"/*.framework; do
    fw_basename=$(basename "$fw_dir")
    fw_name="${fw_basename%.framework}"
    if [ -f "$fw_dir/Versions/A/$fw_name" ]; then
        ln -sf "../Resources/_internal/PyQt6/Qt6/lib/${fw_basename}/Versions/A/${fw_name}" "$fw_name"
        fw_count=$((fw_count + 1))
    fi
done
echo -e "${GREEN}  ✅ Frameworks/ 目录创建 $fw_count 个符号链接${NC}"

# 3. 复制 qt.conf 到 Resources/
cp "$SCRIPT_DIR/qt.conf" "$APP_BUNDLE/Contents/Resources/qt.conf" 2>/dev/null || true

echo -e "${GREEN}  ✅ 资源已同步${NC}"
echo ""

# ----------------------------------------------------------------
# Step 5: 重新签名（ad-hoc 签名，不使用 --deep 避免 TCC 权限提示）
# ----------------------------------------------------------------
echo -e "${YELLOW}[5/7] 签名 .app...${NC}"
# 移除可能残留的 entitlements 和 TCC 记录
xattr -cr "$DIST_DIR/PolySage.app" 2>/dev/null
# 只签主可执行文件，不递归签名嵌入的库（避免触发权限请求）
codesign --force --deep --sign - "$DIST_DIR/PolySage.app" 2>&1 | tail -2
echo -e "${GREEN}  ✅ 签名完成${NC}"
echo ""

# ----------------------------------------------------------------
# Step 6: 生成 .dmg
# ----------------------------------------------------------------
echo -e "${YELLOW}[6/7] 生成 .dmg 安装包...${NC}"

DMG_PATH="$DIST_DIR/$DMG_NAME"
DMG_STAGING="$DIST_DIR/dmg_staging"

rm -rf "$DMG_STAGING" "$DMG_PATH"
mkdir -p "$DMG_STAGING"

cp -r "$DIST_DIR/PolySage.app" "$DMG_STAGING/"
ln -s /Applications "$DMG_STAGING/Applications"

echo -e "${BLUE}  创建磁盘镜像（单步模式，无需挂载）...${NC}"
# 使用单步 hdiutil create，直接生成压缩后的 .dmg，避免 attach/detach 操作
hdiutil create \
    -volname "聚慧 PolySage" \
    -srcfolder "$DMG_STAGING" \
    -ov \
    -fs HFS+ \
    -format UDZO \
    -imagekey zlib-level=9 \
    "$DMG_PATH" 2>&1 | tail -2

rm -rf "$DMG_STAGING"

if [ -f "$DMG_PATH" ]; then
    echo -e "${GREEN}  ✅ .dmg 生成成功${NC}"
else
    echo -e "${RED}❌ .dmg 生成失败${NC}"
    exit 1
fi
echo ""

# ----------------------------------------------------------------
# Step 7: 完成报告
# ----------------------------------------------------------------
echo -e "${YELLOW}[7/7] 打包完成！${NC}"
echo ""
echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}  🎉 打包成功！${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""
echo -e "${GREEN}📦 产物位置：${NC}"
echo -e "  App:  $DIST_DIR/PolySage.app"
echo -e "  DMG:  $DMG_PATH"
echo ""

APP_SIZE=$(du -sh "$DIST_DIR/PolySage.app" 2>/dev/null | cut -f1)
DMG_SIZE=$(du -sh "$DMG_PATH" 2>/dev/null | cut -f1)
echo -e "${GREEN}📊 文件大小：${NC}"
echo -e "  App:  $APP_SIZE"
echo -e "  DMG:  $DMG_SIZE"
echo ""

echo -e "${GREEN}🔧 架构验证：${NC}"
ARCH=$(lipo -archs "$DIST_DIR/PolySage.app/Contents/MacOS/PolySage" 2>/dev/null || echo "unknown")
echo -e "  可执行文件架构: $ARCH"
echo ""

echo -e "${BLUE}💡 安装方法：${NC}"
echo -e "  1. 双击 .dmg 文件挂载"
echo -e "  2. 将 PolySage.app 拖到 Applications 文件夹"
echo -e "  3. 首次打开：右键 → 打开（绕过 Gatekeeper）"
echo -e "  4. 在启动台打开 聚慧 PolySage"
echo ""

# ----------------------------------------------------------------
# Step 8: 触发 Windows .exe 构建（通过 GitHub Actions）
# ----------------------------------------------------------------
# CI 环境（GitHub Actions）中跳过此步骤
if [ -n "$GITHUB_ACTIONS" ]; then
    echo -e "${BLUE}  [CI 环境] 跳过 Windows 构建触发${NC}"
else
echo -e "${YELLOW}[8/8] 构建 Windows .exe 安装包...${NC}"

# 检查是否在 git 仓库中
if git rev-parse --git-dir > /dev/null 2>&1; then
    # 检查 gh CLI 是否安装
    if command -v gh &> /dev/null; then
        # 检查是否已认证
        if gh auth status &> /dev/null 2>&1; then
            echo -e "${BLUE}  通过 GitHub Actions 触发 Windows 构建...${NC}"
            # 获取版本号
            VERSION_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "v1.0.0")
            
            # 触发 workflow
            if gh workflow run release.yml -f version="$VERSION_TAG" 2>/dev/null; then
                echo -e "${GREEN}  ✅ Windows 构建已触发（版本: $VERSION_TAG）${NC}"
                echo -e "${BLUE}  等待构建完成...${NC}"
                
                # 等待 workflow 启动
                sleep 5
                
                # 获取最新的 workflow run
                RUN_ID=$(gh run list --workflow=release.yml --limit=1 --json databaseId -q '.[0].databaseId' 2>/dev/null)
                
                if [ -n "$RUN_ID" ]; then
                    echo -e "${BLUE}  Workflow Run ID: $RUN_ID${NC}"
                    echo -e "${BLUE}  监听构建进度（可按 Ctrl+C 跳过等待）...${NC}"
                    
                    # 监听构建（超时20分钟）
                    timeout 1200 gh run watch "$RUN_ID" --exit-status 2>/dev/null || true
                    
                    # 检查构建结果
                    RUN_STATUS=$(gh run view "$RUN_ID" --json conclusion -q '.conclusion' 2>/dev/null || echo "unknown")
                    
                    if [ "$RUN_STATUS" = "success" ]; then
                        echo -e "${GREEN}  ✅ Windows 构建成功！正在下载 .exe...${NC}"
                        
                        # 下载 Windows 产物
                        gh run download "$RUN_ID" -n windows-exe -D "$DIST_DIR/windows" 2>/dev/null || true
                        
                        # 查找下载的 .exe
                        EXE_FILE=$(find "$DIST_DIR/windows" -name "*.exe" -type f 2>/dev/null | head -1)
                        if [ -n "$EXE_FILE" ]; then
                            EXE_SIZE=$(du -sh "$EXE_FILE" 2>/dev/null | cut -f1)
                            echo -e "${GREEN}  ✅ Windows .exe 已下载${NC}"
                            echo -e "  EXE: $EXE_FILE ($EXE_SIZE)"
                        else
                            echo -e "${YELLOW}  ⚠️  产物下载完成但未找到 .exe 文件${NC}"
                            echo -e "${BLUE}  可手动从 GitHub Actions 页面下载${NC}"
                        fi
                    else
                        echo -e "${YELLOW}  ⚠️  Windows 构建状态: $RUN_STATUS${NC}"
                        echo -e "${BLUE}  可手动从 GitHub Actions 页面查看和下载${NC}"
                        echo -e "${BLUE}  https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/actions${NC}"
                    fi
                else
                    echo -e "${YELLOW}  ⚠️  无法获取 Workflow Run ID${NC}"
                    echo -e "${BLUE}  请手动查看: https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/actions${NC}"
                fi
            else
                echo -e "${YELLOW}  ⚠️  无法触发 GitHub Actions workflow${NC}"
                echo -e "${BLUE}  请确保 .github/workflows/release.yml 已推送到仓库${NC}"
            fi
        else
            echo -e "${YELLOW}  ⚠️  GitHub CLI 未认证，跳过 Windows 构建${NC}"
            echo -e "${BLUE}  运行 'gh auth login' 认证后可自动构建 Windows .exe${NC}"
            echo -e "${BLUE}  或手动推送 tag 触发: git tag v1.0.0 && git push origin v1.0.0${NC}"
        fi
    else
        echo -e "${YELLOW}  ⚠️  未安装 GitHub CLI (gh)，跳过 Windows 构建${NC}"
        echo -e "${BLUE}  安装: brew install gh${NC}"
        echo -e "${BLUE}  或手动推送 tag 触发: git tag v1.0.0 && git push origin v1.0.0${NC}"
    fi
else
    echo -e "${YELLOW}  ⚠️  不在 git 仓库中，跳过 Windows 构建${NC}"
    echo -e "${BLUE}  初始化 git 仓库并推送到 GitHub 后可自动构建 Windows .exe${NC}"
fi
fi  # 结束 GITHUB_ACTIONS 判断
echo ""
