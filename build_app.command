#!/bin/bash
# ============================================================
# 聚慧 PolySage — 一键生成 .app（仅 macOS ARM64）
#
# 双击此文件即可运行，只生成 dist/聚慧.app，不生成 .dmg
# ============================================================
set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  🪑 聚慧 PolySage — 生成 .app (ARM64)${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# 切换到脚本所在目录（app/ 目录）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/app"

APP_DIR="$SCRIPT_DIR/app"
DIST_DIR="$APP_DIR/dist"
BUILD_DIR="$APP_DIR/build"

# ----------------------------------------------------------------
# Step 0: 预检查 — 确保代码能正常导入
# ----------------------------------------------------------------
echo -e "${YELLOW}[0/6] 检查代码...${NC}"

# 找到 python3
PYTHON3=""
for py in python3 python3.10 python3.11 python3.12; do
    if command -v "$py" &> /dev/null; then
        PYTHON3="$py"
        break
    fi
done

if [ -z "$PYTHON3" ]; then
    echo -e "${RED}❌ 未找到 python3，请先安装 Python 3.10+${NC}"
    echo -e "${BLUE}  安装方法: brew install python@3.10${NC}"
    echo "按回车键退出..."
    read
    exit 1
fi

PY_ARCH=$($PYTHON3 -c "import platform; print(platform.machine())")
echo -e "${GREEN}  ✅ Python $($PYTHON3 --version | cut -d' ' -f2) ($PY_ARCH)${NC}"

if [ "$PY_ARCH" != "arm64" ]; then
    echo -e "${RED}❌ 当前 Python 架构为 $PY_ARCH，需要 arm64${NC}"
    echo -e "${BLUE}  请安装 ARM64 原生 Python: brew install python@3.10${NC}"
    echo "按回车键退出..."
    read
    exit 1
fi

# 检查代码能否导入（防止打包后启动崩溃）
echo -e "${YELLOW}  ⏳ 检查代码能否导入...${NC}"
$PYTHON3 -c "
import sys
sys.path.insert(0, '.')
try:
    import ui_main_window
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" 2>&1 | grep -q "OK"
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ 代码导入失败，打包会崩溃！${NC}"
    echo -e "${YELLOW}  请修复后再试。常见原因: 缩进错误(self在类体中)${NC}"
    $PYTHON3 -c "
import sys
sys.path.insert(0, '.')
try:
    import ui_main_window
except Exception as e:
    print(f'  错误: {e}')
" 2>&1
    echo ""
    echo "按回车键退出..."
    read
    exit 1
fi
echo -e "${GREEN}  ✅ 代码检查通过${NC}"

echo ""

# ----------------------------------------------------------------
# Step 1: 安装依赖
# ----------------------------------------------------------------
echo -e "${YELLOW}[1/6] 安装依赖...${NC}"

$PYTHON3 -m pip install -r requirements.txt --break-system-packages -q 2>&1 | tail -3
echo -e "${GREEN}  ✅ 项目依赖已就绪${NC}"

if ! $PYTHON3 -c "import PyInstaller" 2>/dev/null; then
    echo -e "${YELLOW}  ⏳ 安装 PyInstaller 6.3.0...${NC}"
    $PYTHON3 -m pip install pyinstaller==6.3.0 --break-system-packages -q
fi
echo -e "${GREEN}  ✅ PyInstaller $($PYTHON3 -m PyInstaller --version)${NC}"

echo ""

# ----------------------------------------------------------------
# Step 2: 清理旧产物
# ----------------------------------------------------------------
echo -e "${YELLOW}[2/6] 清理旧产物...${NC}"
xattr -cr "$BUILD_DIR" "$DIST_DIR" 2>/dev/null || true
chflags -R nouchg "$BUILD_DIR" "$DIST_DIR" 2>/dev/null || true
rm -rf "$BUILD_DIR" "$DIST_DIR"
find "$APP_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
echo -e "${GREEN}  ✅ 已清理${NC}"

echo ""

# ----------------------------------------------------------------
# Step 3: PyInstaller 打包
# ----------------------------------------------------------------
echo -e "${YELLOW}[3/6] PyInstaller 打包中（ARM64）...${NC}"
echo -e "${BLUE}  这可能需要几分钟...${NC}"

export PYINSTALLER_CONFIG_DIR="${TMPDIR:-/tmp}/pyinstaller_cache"
mkdir -p "$PYINSTALLER_CONFIG_DIR"

$PYTHON3 -m PyInstaller \
    --noconfirm \
    --clean \
    --target-arch arm64 \
    --windowed \
    --osx-bundle-identifier com.polysage.app \
    --name "聚慧" \
    --icon AppIcon.icns \
    --add-data "logo_ui.png:." \
    --add-data "logo_ui@2x.png:." \
    main.py \
    ui_main_window.py \
    ui_widgets.py \
    ui_worker.py \
    ui_flowlayout.py \
    ui_styles.py \
    browser.py \
    core.py \
    config_manager.py \
    utils.py \
    logger.py \
    platform_adapter.py \
    macos_adapter.py \
    windows_adapter.py \
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
    --hidden-import platform_adapter \
    --hidden-import macos_adapter \
    --hidden-import windows_adapter \
    --collect-submodules PyQt6 \
    --collect-binaries PyQt6 \
    --collect-all playwright \
    --collect-data qasync \
    --copy-metadata openai \
    --copy-metadata qasync \
    --exclude-module PyQt6.Qt6 \
    --exclude-module tkinter \
    --exclude-module matplotlib \
    --exclude-module numpy \
    --exclude-module pandas \
    --exclude-module PIL \
    --exclude-module PyQt5 \
    --exclude-module PySide6 \
    --exclude-module PyQt6.Qt3DCore \
    --exclude-module PyQt6.Qt3DRender \
    --exclude-module PyQt6.Qt3DAnimation \
    --exclude-module PyQt6.Qt3DExtras \
    --exclude-module PyQt6.Qt3DInput \
    --exclude-module PyQt6.Qt3DLogic \
    --exclude-module PyQt6.QtBluetooth \
    --exclude-module PyQt6.QtCharts \
    --exclude-module PyQt6.QtDataVisualization \
    --exclude-module PyQt6.QtDesigner \
    --exclude-module PyQt6.QtHelp \
    --exclude-module PyQt6.QtMultimedia \
    --exclude-module PyQt6.QtMultimediaWidgets \
    --exclude-module PyQt6.QtNetwork \
    --exclude-module PyQt6.QtNfc \
    --exclude-module PyQt6.QtOpenGL \
    --exclude-module PyQt6.QtOpenGLWidgets \
    --exclude-module PyQt6.QtPdf \
    --exclude-module PyQt6.QtPdfWidgets \
    --exclude-module PyQt6.QtPositioning \
    --exclude-module PyQt6.QtPrintSupport \
    --exclude-module PyQt6.QtQml \
    --exclude-module PyQt6.QtQuick \
    --exclude-module PyQt6.QtQuick3D \
    --exclude-module PyQt6.QtQuickControls2 \
    --exclude-module PyQt6.QtQuickWidgets \
    --exclude-module PyQt6.QtRemoteObjects \
    --exclude-module PyQt6.QtSensors \
    --exclude-module PyQt6.QtSerialPort \
    --exclude-module PyQt6.QtSpatialAudio \
    --exclude-module PyQt6.QtSql \
    --exclude-module PyQt6.QtTest \
    --exclude-module PyQt6.QtTextToSpeech \
    --exclude-module PyQt6.QtWebChannel \
    --exclude-module PyQt6.QtWebEngineCore \
    --exclude-module PyQt6.QtWebEngineQuick \
    --exclude-module PyQt6.QtWebEngineWidgets \
    --exclude-module PyQt6.QtWebSockets \
    --exclude-module PyQt6.QtXml \
    2>&1 | tail -10

if [ ! -d "$DIST_DIR/聚慧.app" ]; then
    echo -e "${RED}❌ 打包失败${NC}"
    echo "按回车键退出..."
    read
    exit 1
fi
echo -e "${GREEN}  ✅ .app 打包成功${NC}"

echo ""

# ----------------------------------------------------------------
# Step 4: 优化 Qt6 Framework
# ----------------------------------------------------------------
echo -e "${YELLOW}[4/6] 优化 Qt6 framework...${NC}"

APP_BUNDLE="$DIST_DIR/聚慧.app"
APP_FW="$APP_BUNDLE/Contents/Frameworks"
APP_QT6LIB="$APP_FW/PyQt6/Qt6/lib"

QT6_LIB=$($PYTHON3 -c "
import PyQt6, os
qt6_dir = os.path.join(os.path.dirname(PyQt6.__file__), 'Qt6', 'lib')
print(qt6_dir)
" 2>&1) || { echo "  ⚠️ 获取 QT6_LIB 失败: $QT6_LIB"; QT6_LIB=""; }

if [ -n "$QT6_LIB" ] && [ -d "$QT6_LIB" ]; then
    # 重新复制 4 个实际使用的 framework
    for fw in QtCore QtGui QtWidgets QtDBus; do
        rm -rf "$APP_QT6LIB/$fw.framework"
        cp -R "$QT6_LIB/$fw.framework" "$APP_QT6LIB/"
        echo "  修复 Qt6/$fw framework ✓"
    done
    # 删除其余 framework
    for fw_dir in "$APP_QT6LIB"/*.framework; do
        fw_name=$(basename "$fw_dir" .framework)
        case "$fw_name" in
            QtCore|QtGui|QtWidgets|QtDBus) ;;
            *) rm -rf "$fw_dir" ;;
        esac
    done
    echo -e "${GREEN}  ✅ Qt6 framework 已优化（仅保留 4 个）${NC}"
else
    echo -e "${YELLOW}  ⚠️  Qt6 库未找到${NC}"
fi

# 清理断裂符号链接
find "$APP_FW" -type l ! -exec test -e {} \; -delete 2>/dev/null || true

# 删除 COLLECT 残留
rm -rf "$DIST_DIR/聚慧"

# 同步资源
cp "$APP_DIR/Info.plist" "$APP_BUNDLE/Contents/Info.plist"
cp "$APP_DIR/AppIcon.icns" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"
cp "$APP_DIR/qt.conf" "$APP_BUNDLE/Contents/Resources/qt.conf" 2>/dev/null || true
echo -e "${GREEN}  ✅ 资源已同步${NC}"

# 创建 Qt6 符号链接
echo -e "${BLUE}  创建 Qt6 符号链接...${NC}"

cd "$APP_QT6LIB"
for fw_dir in *.framework; do
    fw_name="${fw_dir%.framework}"
    if [ -f "$fw_dir/Versions/A/$fw_name" ]; then
        ln -sf "$fw_dir/Versions/A/$fw_name" "$fw_name"
    fi
done

cd "$APP_FW"
for f in Qt*; do
    [ -L "$f" ] && rm "$f"
done
for fw_dir in "$APP_QT6LIB"/*.framework; do
    fw_basename=$(basename "$fw_dir")
    fw_name="${fw_basename%.framework}"
    if [ -f "$fw_dir/Versions/A/$fw_name" ]; then
        ln -sf "PyQt6/Qt6/lib/${fw_basename}/Versions/A/${fw_name}" "$fw_name"
    fi
done
echo -e "${GREEN}  ✅ 符号链接已创建${NC}"

echo ""

# ----------------------------------------------------------------
# Step 5: 签名
# ----------------------------------------------------------------
echo -e "${YELLOW}[5/6] 签名 .app...${NC}"
xattr -cr "$APP_BUNDLE" 2>/dev/null || true
codesign --force --deep --sign - "$APP_BUNDLE" 2>&1 | tail -2 || true
echo -e "${GREEN}  ✅ 签名完成${NC}"

# 签名后创建 _internal 符号链接
ln -sf ../Frameworks "$APP_BUNDLE/Contents/Resources/_internal"
if [ -L "$APP_BUNDLE/Contents/Resources/_internal" ]; then
    echo -e "${GREEN}  ✅ _internal 符号链接已创建${NC}"
else
    echo -e "${RED}  ❌ _internal 符号链接创建失败${NC}"
fi

echo ""

# ----------------------------------------------------------------
# Step 6: 验证
# ----------------------------------------------------------------
echo -e "${YELLOW}[6/6] 验证...${NC}"

APP_SIZE=$(du -sh "$APP_BUNDLE" 2>/dev/null | cut -f1)
ARCH=$(lipo -archs "$APP_BUNDLE/Contents/MacOS/聚慧" 2>/dev/null || echo "unknown")

echo -e "${GREEN}  📦 大小: $APP_SIZE${NC}"
echo -e "${GREEN}  🔧 架构: $ARCH${NC}"

# 验证签名
if codesign --verify --deep --strict "$APP_BUNDLE" 2>/dev/null; then
    echo -e "${GREEN}  ✅ 签名验证通过${NC}"
else
    echo -e "${YELLOW}  ⚠️  签名验证未通过（ad-hoc 签名，首次打开需右键→打开）${NC}"
fi

echo ""
echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}  🎉 生成完成！${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""
echo -e "${GREEN}📦 产物位置:${NC}"
echo -e "  $APP_BUNDLE"
echo ""
echo -e "${BLUE}💡 安装方法:${NC}"
echo -e "  1. 在 Finder 中打开 dist 文件夹"
echo -e "  2. 将 聚慧.app 拖到 Applications 文件夹"
echo -e "  3. 首次打开：右键 → 打开（绕过 Gatekeeper）"
echo ""

# 自动在 Finder 中打开 dist 目录
open "$DIST_DIR"

echo "按回车键退出..."
read
