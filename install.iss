; AI 团队群聊 · 桌面版 安装脚本
; 使用 Inno Setup 6 编译：ISCC.exe install.iss

#define MyAppName "AI团队群聊"
; 改版本号时三处一起改：这里的 MyAppVersion、下面的 OutputBaseFilename、
; 以及 app_config.py 的 APP_VERSION。tests/test_config.py 的 I 节会拿它们对账。
#define MyAppVersion "1.2.1"
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
; 文件名用英文 + 短版本号，跟 GitHub Release 上的资产名一一对应。
; 为什么不能用中文名：GitHub 会把资产名里的非 ASCII 字符换成点，
; "AI团队群聊-安装程序-v1.2.exe" 上传后变成 "AI.-.-v1.2.exe"，
; 于是 README 里写的下载名和用户在 Release 页看到的对不上（v1.1 就这么错了一版）。
; 本地构建产物直接叫这个名字，发版时不需要再手工改名。
OutputBaseFilename=AI-Group-Chat-Setup-v1.2.1
; 管理员权限（写 D 盘根目录需要）
PrivilegesRequired=admin
; 支持中文
ShowLanguageDialog=no
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription=AI 团队群聊 · 桌面版
VersionInfoProductName=AI团队群聊

[Languages]
; 语言包取自 Inno Setup 官方源码树 Files/Languages/ChineseSimplified.isl
; （维护者 Zhenghan Yang / Kira，UTF-8），随仓库一起带上，构建不依赖本机装没装中文包。
; 以前这里写的是 compiler:Default.isl —— 那是**英文**包，于是挂了个"chinesesimplified"
; 的名字、向导却全英文，而 README 首页写着"全中文界面"。
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
; 快捷方式默认全部创建（Inno 静默安装时需显式传 /TASKS，实测不传会跳过——因此下面[Icons]改为无条件创建）

[Files]
; 主程序整个 dist 目录（PyInstaller 产物）
Source: "dist\AI团队群聊\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} 卸载"; Filename: "{uninstallexe}"
; 桌面快捷方式放"公共桌面"，不放 {userdesktop}。
; 原因：Inno Setup 6.3 起默认开启 RedirectionGuard，禁止穿过**不受信任的装入点**
; 读写。用户的桌面如果是 junction（这台机器上就是：
; C:\Users\32303\Desktop -> D:\C-Migrate\Desktop，迁移工具干的），创建快捷方式
; 会以这个错直接中断整个安装：
;     IPersistFile::Save failed; code 0x800701C0
;     无法遍历该路径，因为它包含不受信任的装入点。
; 公共桌面（C:\Users\Public\Desktop）是普通目录，不踩这个坑，而且它照样显示在
; 每个用户的桌面上。顺带消掉"PrivilegesRequired=admin 却用了 per-user 的
; userdesktop"那条编译器警告。
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent