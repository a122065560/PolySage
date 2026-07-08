; ============================================================
; PolySage（聚慧）Windows 安装包脚本 - Inno Setup
; ------------------------------------------------------------
; 使用方式（命令行传入版本号）:
;   iscc /DMyAppVersion=v1.0.0 installer.iss
;
; 未传入版本号时默认使用 v1.0.0
; 输出文件: PolySage-{版本号}-Windows.exe
; ============================================================

; 版本号定义（可通过命令行 /DMyAppVersion 覆盖）
#ifndef MyAppVersion
  #define MyAppVersion "v1.0.0"
#endif

[Setup]
; 应用名称
AppName=聚慧 PolySage
; 应用版本（显示在控制面板）
AppVersion={#MyAppVersion}
; 发布者
AppPublisher=PolySage
; 默认安装目录（{autopf} 自动选择 64 位 Program Files）
DefaultDirName={autopf}\PolySage
; 默认开始菜单组名
DefaultGroupName=聚慧 PolySage
; 仅支持 64 位 Windows
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
; 输出目录（当前目录，即仓库根目录）
OutputDir=.
; 输出文件名
OutputBaseFilename=PolySage-{#MyAppVersion}-Windows
; 压缩方式（LZMA2 最高压缩比）
Compression=lzma2
SolidCompression=yes
; 使用现代向导界面
WizardStyle=modern
; 卸载时显示的图标
UninstallDisplayIcon={app}\PolySage.exe
; 安装需要管理员权限（写入 Program Files）
PrivilegesRequired=admin
; 不显示语言选择对话框（默认简体中文）
ShowLanguageDialog=no

[Languages]
; 简体中文（默认）
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
; 英文
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; 创建桌面快捷方式（默认勾选）
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: checkedonce
; 创建开始菜单快捷方式（默认勾选）
Name: "startmenu"; Description: "创建开始菜单快捷方式"; GroupDescription: "附加任务:"; Flags: checkedonce

[Files]
; 打包 PyInstaller 输出的所有文件（递归包含子目录）
Source: "roundtableai\dist\PolySage\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
; 开始菜单快捷方式
Name: "{group}\聚慧 PolySage"; Filename: "{app}\PolySage.exe"; IconFilename: "{app}\PolySage.exe"
; 桌面快捷方式（仅当用户勾选桌面快捷方式任务时创建）
Name: "{commondesktop}\聚慧 PolySage"; Filename: "{app}\PolySage.exe"; IconFilename: "{app}\PolySage.exe"; Tasks: desktopicon

[Run]
; 安装完成后可选立即启动应用
Filename: "{app}\PolySage.exe"; Description: "立即启动 聚慧 PolySage"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时清理本地应用数据目录
Type: filesandordirs; Name: "{%LOCALAPPDATA}\PolySage"
