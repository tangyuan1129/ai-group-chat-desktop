; AI 团队群聊 · 桌面版 安装脚本
; 使用 Inno Setup 6 编译：ISCC.exe install.iss

#define MyAppName "AI团队群聊"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "J1129"
#define MyAppExeName "AI团队群聊.exe"
#define MyAppAssocName MyAppName + " 文件"

[Setup]
; 安装程序基本信息
AppId={{8C5F3B2A-7D4E-4E9F-9C4D-A10000000001}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName=D:\AI团队群聊
DefaultGroupName=AI团队群聊
DisableProgramGroupPage=yes
; 必须有卸载程序
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} 卸载
; 压缩与输出
Compression=lzma2/max
SolidCompression=yes
OutputDir=..\
OutputBaseFilename=AI团队群聊-安装程序-v1.0
; 管理员权限（写 D 盘根目录需要）
PrivilegesRequired=admin
; 支持中文
ShowLanguageDialog=no
VersionInfoVersion=1.0.0
VersionInfoDescription=AI 团队群聊 · 桌面版
VersionInfoProductName=AI团队群聊

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Default.isl"

[Tasks]
; 快捷方式默认全部创建（Inno 静默安装时需显式传 /TASKS，实测不传会跳过——因此下面[Icons]改为无条件创建）

[Files]
; 主程序整个 dist 目录（PyInstaller 产物）
Source: "dist\AI团队群聊\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} 卸载"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent