; ============================================================
; PolySage（聚慧）Windows 安装包脚本 - Inno Setup
; ------------------------------------------------------------
; 编译命令: iscc /DMyAppVersion=v1.0.0 installer.iss
; 产物: PolySage-{version}-Windows.exe
; ============================================================

#define MyAppName "聚慧 PolySage"
#define MyAppPublisher "PolySage"
#define MyAppURL "https://github.com/a122065560/PolySage"
#define MyAppExeName "PolySage.exe"

[Setup]
AppId={{B8F3A2E1-7C4D-4E9F-A1B2-C3D4E5F6A7B8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\PolySage
DefaultGroupName=聚慧 PolySage
DisableProgramGroupPage=yes
OutputDir=.
OutputBaseFilename=PolySage-{#MyAppVersion}-Windows
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName=聚慧 PolySage

; 中文界面
ShowLanguageDialog=no
LinguisticsFile=compiler:Languages\ChineseSimplified.isl

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "在桌面创建快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce

[Files]
; PyInstaller 产物目录
Source: "roundtableai\dist\PolySage\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 聚慧 PolySage"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时清理用户数据目录（可选）
Type: filesandordirs; Name: "{localappdata}\PolySage"; Flags: ignoreversion
