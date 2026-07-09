#!/bin/bash
# ============================================================
# 聚慧 PolySage — 一键生成 .app（仅 macOS ARM64）
#
# 双击此文件即可运行，只生成 dist/聚慧.app，不生成 .dmg
# ============================================================

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

# 切换到脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/app"

APP_DIR="$SCRIPT_DIR/app"
DIST_DIR="$APP_DIR/dist"
BUILD_DIR="$APP_DIR/build"

# ============================================================
# 函数: 测试某个 Python 能否 import PyQt6
# 参数: $1 = python 可执行文件路径
#       $2 = PYTHONHOME 值(可选,为空则不设置)
# ============================================================
test_python() {
    local py_path="$1"
    local py_home="$2"

    # 必须能真正加载 Qt 模块(不只是 import __init__)
    if [ -n "$py_home" ]; then
        env -u PYTHONPATH PYTHONHOME="$py_home" "$py_path" -c "from PyQt6 import QtWidgets, QtCore; print('OK')" 2>/dev/null
    else
        env -u PYTHONHOME -u PYTHONPATH "$py_path" -c "from PyQt6 import QtWidgets, QtCore; print('OK')" 2>/dev/null
    fi
}

# ============================================================
# 函数: 运行 Python 命令(使用已找到的 PYTHON3 + PYTHON_HOME)
# ============================================================
run_python() {
    if [ -n "$PYTHON_HOME" ]; then
        env -u PYTHONPATH PYTHONHOME="$PYTHON_HOME" "$PYTHON3" "$@"
    else
        env -u PYTHONHOME -u PYTHONPATH "$PYTHON3" "$@"
    fi
}

# ----------------------------------------------------------------
# Step 0: 找到有 PyQt6 的 Python
# ----------------------------------------------------------------
echo -e "${YELLOW}[0/6] 查找 Python...${NC}"

PYTHON3=""
PYTHON_HOME=""
PYTHON_FOUND=""

# --- 候选 1: 常规 Python (Homebrew / 系统 / 用户安装) ---
CANDIDATES=(
    "/opt/homebrew/bin/python3"
    "/opt/homebrew/bin/python3.10"
    "/opt/homebrew/bin/python3.11"
    "/opt/homebrew/bin/python3.12"
    "/usr/local/bin/python3"
    "$HOME/.local/bin/python3"
    "$HOME/.local/bin/python3.11"
    "$HOME/.local/bin/python3.10"
    "/usr/bin/python3"
)

for py in "${CANDIDATES[@]}"; do
    if [ ! -x "$py" ]; then
        continue
    fi

    # 检查架构
    PY_ARCH=$(env -u PYTHONHOME -u PYTHONPATH "$py" -c "import platform; print(platform.machine())" 2>/dev/null)
    if [ "$PY_ARCH" != "arm64" ]; then
        continue
    fi

    # 尝试直接 import PyQt6 (不设 PYTHONHOME)
    if test_python "$py" ""; then
        PYTHON3="$py"
        PYTHON_HOME=""
        PYTHON_FOUND=$(env -u PYTHONHOME -u PYTHONPATH "$py" --version 2>&1)
        echo -e "${GREEN}  ✅ 找到: $PYTHON_FOUND ($PY_ARCH)${NC}"
        echo -e "${BLUE}  路径: $py${NC}"
        break
    fi
done

# --- 候选 2: TRAE 管理的 Python 3.10 ---
if [ -z "$PYTHON3" ]; then
    TRAE_BASE="$HOME/Library/Application Support/TRAE SOLO CN/ModularData/ai-agent/vm/tools"

    # 查找 TRAE Python 3.10 的所有版本
    if [ -d "$TRAE_BASE/opt" ]; then
        for version_dir in "$TRAE_BASE/opt/python@3.10"/*/; do
            [ ! -d "$version_dir" ] && continue

            TRAE_PY_BIN="${version_dir}libexec/bin/python3"
            TRAE_PY_HOME="${version_dir}Frameworks/Python.framework/Versions/3.10"

            if [ ! -x "$TRAE_PY_BIN" ]; then
                continue
            fi

            # 检查架构
            PY_ARCH=$(env -u PYTHONPATH PYTHONHOME="$TRAE_PY_HOME" "$TRAE_PY_BIN" -c "import platform; print(platform.machine())" 2>/dev/null)
            if [ "$PY_ARCH" != "arm64" ]; then
                continue
            fi

            # 检查 PyQt6
            if test_python "$TRAE_PY_BIN" "$TRAE_PY_HOME"; then
                PYTHON3="$TRAE_PY_BIN"
                PYTHON_HOME="$TRAE_PY_HOME"
                PYTHON_FOUND=$(env -u PYTHONPATH PYTHONHOME="$TRAE_PY_HOME" "$TRAE_PY_BIN" --version 2>&1)
                echo -e "${GREEN}  ✅ 找到: $PYTHON_FOUND ($PY_ARCH) [TRAE]${NC}"
                echo -e "${BLUE}  路径: $TRAE_PY_BIN${NC}"
                break
            fi
        done
    fi
fi

# --- 候选 3: PATH 中的 python3 (可能被 TRAE wrapper 包裹) ---
if [ -z "$PYTHON3" ]; then
    for py in python3 python3.10 python3.11 python3.12; do
        PY_PATH=$(command -v "$py" 2>/dev/null)
        if [ -z "$PY_PATH" ] || [ ! -x "$PY_PATH" ]; then
            continue
        fi

        # 检查架构 (清除环境变量)
        PY_ARCH=$(env -u PYTHONHOME -u PYTHONPATH "$PY_PATH" -c "import platform; print(platform.machine())" 2>/dev/null)
        if [ "$PY_ARCH" != "arm64" ]; then
            continue
        fi

        # 尝试直接运行
        if test_python "$PY_PATH" ""; then
            PYTHON3="$PY_PATH"
            PYTHON_HOME=""
            PYTHON_FOUND=$(env -u PYTHONHOME -u PYTHONPATH "$PY_PATH" --version 2>&1)
            echo -e "${GREEN}  ✅ 找到: $PYTHON_FOUND ($PY_ARCH)${NC}"
            echo -e "${BLUE}  路径: $PY_PATH${NC}"
            break
        fi
    done
fi

# --- 如果都没找到 ---
if [ -z "$PYTHON3" ]; then
    echo -e "${RED}❌ 未找到已安装 PyQt6 的 Python${NC}"
    echo ""
    echo -e "${YELLOW}解决方案 (选一个):${NC}"
    echo ""
    echo -e "${BLUE}方案 A: 安装 Homebrew + Python 3.10${NC}"
    echo -e "  1. 安装 Homebrew:    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo -e "  2. 安装 Python:      brew install python@3.10"
    echo -e "  3. 安装依赖:         /opt/homebrew/bin/python3.10 -m pip install PyQt6==6.6.1 PyQt6-Qt6==6.6.1 qasync==0.27.1 playwright==1.40.0 openai==1.12.0"
    echo -e "  4. 再次双击此脚本"
    echo ""
    echo -e "${BLUE}方案 B: 用现有 Python 安装依赖${NC}"
    echo -e "  1. python3 -m pip install PyQt6==6.6.1 PyQt6-Qt6==6.6.1 qasync==0.27.1 playwright==1.40.0 openai==1.12.0 --break-system-packages"
    echo -e "  2. 再次双击此脚本"
    echo ""
    echo "脚本结束。按回车键关闭窗口..."
    read
    exit 1
fi

# 验证架构
PY_ARCH=$(run_python -c "import platform; print(platform.machine())" 2>/dev/null)
if [ "$PY_ARCH" != "arm64" ]; then
    echo -e "${RED}❌ Python 架构为 $PY_ARCH，需要 arm64${NC}"
    echo "脚本结束。按回车键关闭窗口..."
    read
    exit 1
fi

echo ""

# ----------------------------------------------------------------
# Step 0b: 检查代码能否导入
# ----------------------------------------------------------------
echo -e "${YELLOW}  检查代码能否导入...${NC}"

IMPORT_CHECK=$(run_python -c "
import sys
sys.path.insert(0, '.')
try:
    import ui_main_window
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" 2>&1)

if echo "$IMPORT_CHECK" | grep -q "^OK$"; then
    echo -e "${GREEN}  ✅ 代码检查通过${NC}"
else
    echo -e "${RED}❌ 代码导入失败，打包后无法启动！${NC}"
    echo -e "${YELLOW}  错误详情:${NC}"
    echo "  $IMPORT_CHECK"
    echo ""
    echo -e "${YELLOW}  常见原因: 缩进错误(self在类体中)${NC}"
    echo ""
    echo "脚本结束。按回车键关闭窗口..."
    read
    exit 1
fi

echo ""

# ----------------------------------------------------------------
# Step 1: 安装/更新依赖
# ----------------------------------------------------------------
echo -e "${YELLOW}[1/6] 检查依赖...${NC}"
run_python -m pip install -r requirements.txt --break-system-packages -q 2>&1 | tail -3

if ! run_python -c "import PyInstaller" 2>/dev/null; then
    echo -e "${YELLOW}  安装 PyInstaller 6.3.0...${NC}"
    run_python -m pip install pyinstaller==6.3.0 --break-system-packages -q
fi
echo -e "${GREEN}  ✅ PyInstaller $(run_python -m PyInstaller --version 2>/dev/null)${NC}"

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

run_python -m PyInstaller \
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
    echo ""
    echo "脚本结束。按回车键关闭窗口..."
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

QT6_LIB=$(run_python -c "
import PyQt6, os
qt6_dir = os.path.join(os.path.dirname(PyQt6.__file__), 'Qt6', 'lib')
print(qt6_dir)
" 2>&1) || { echo "  ⚠️ 获取 QT6_LIB 失败: $QT6_LIB"; QT6_LIB=""; }

if [ -n "$QT6_LIB" ] && [ -d "$QT6_LIB" ]; then
    for fw in QtCore QtGui QtWidgets QtDBus; do
        rm -rf "$APP_QT6LIB/$fw.framework"
        cp -R "$QT6_LIB/$fw.framework" "$APP_QT6LIB/"
        echo "  修复 Qt6/$fw framework ✓"
    done
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

find "$APP_FW" -type l ! -exec test -e {} \; -delete 2>/dev/null || true
rm -rf "$DIST_DIR/聚慧"

cp "$APP_DIR/Info.plist" "$APP_BUNDLE/Contents/Info.plist"
cp "$APP_DIR/AppIcon.icns" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"
cp "$APP_DIR/qt.conf" "$APP_BUNDLE/Contents/Resources/qt.conf" 2>/dev/null || true
echo -e "${GREEN}  ✅ 资源已同步${NC}"

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

echo "按回车键关闭窗口..."
read
