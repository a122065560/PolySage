; ============================================================
; PolySage（聚慧）Windows 安装包脚本 - Inno Setup
; ------------------------------------------------------------
; 编译命令: iscc /DMyAppVersion=v1.0.0 installer.iss
; 产物: PolySage-{version}-Windows.exe
; ============================================================

#define MyAppName "聚慧"
#define MyAppPublisher "PolySage"
#define MyAppURL "https://github.com/a122065560/PolySage"
#define MyAppExeName "聚慧.exe"

[Setup]
AppId={{B8F3A2E1-7C4D-4E9F-A1B2-C3D4E5F6A7B8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\聚慧
DefaultGroupName=聚慧
DisableProgramGroupPage=yes
OutputDir=.
OutputBaseFilename=聚慧-{#MyAppVersion}-Windows
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName=聚慧

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; PyInstaller 产物目录
Source: "..\app\dist\聚慧\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch 聚慧"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时清理用户数据目录
Type: filesandordirs; Name: "{localappdata}\PolySage"
