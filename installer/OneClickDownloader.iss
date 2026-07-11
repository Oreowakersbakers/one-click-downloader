#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

#define AppName "One-Click Downloader"
#define AppPublisher "Oreowakersbakers"
#define AppExeName "One-Click Downloader.exe"

[Setup]
AppId={{7FC4EA20-A9D5-4E72-AADB-A9D7D925B178}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\One-Click Downloader
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=OneClickDownloader-{#AppVersion}-Setup
SetupIconFile=..\oneclickdl\assets\oneclick.ico
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}

[Files]
Source: "..\dist\One-Click Downloader.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\extension\*"; DestDir: "{app}\browser-extension"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "startup"; Description: "Start One-Click Downloader when I sign in"; GroupDescription: "Startup:"

[Registry]
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "OneClickDownloader"; ValueData: """{app}\{#AppExeName}"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
Filename: "explorer.exe"; Parameters: """{app}\browser-extension"""; Description: "Open the browser extension package folder"; Flags: nowait postinstall skipifsilent unchecked
