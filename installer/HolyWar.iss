#define AppName "Holy War"
#define AppPublisher "Holy War Team"
#define AppExeName "HolyWar.exe"
#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif

[Setup]
AppId={{9B11A38C-9033-4CF0-8F25-33E819E4BA7A}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\Holy War
DefaultGroupName=Holy War
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=HolyWar-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "Crea un collegamento sul desktop"; GroupDescription: "Collegamenti aggiuntivi:"

[Files]
Source: "..\dist\HolyWar\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "vendor\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: not IsWebView2Installed

[Icons]
Name: "{autoprograms}\Holy War"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\Holy War"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon; WorkingDir: "{app}"

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installazione di Microsoft WebView2..."; Flags: waituntilterminated; Check: not IsWebView2Installed
Filename: "{app}\{#AppExeName}"; Description: "Avvia Holy War"; Flags: nowait postinstall skipifsilent; WorkingDir: "{app}"

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\HolyWar"
Type: filesandordirs; Name: "{localappdata}\HolyWar"
Type: filesandordirs; Name: "{localappdata}\Temp\HolyWar"

[Code]
function IsWebView2Installed: Boolean;
var
  Version: String;
  RuntimeKey: String;
begin
  RuntimeKey := 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result :=
    (RegQueryStringValue(HKLM32, RuntimeKey, 'pv', Version) and
      (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, RuntimeKey, 'pv', Version) and
      (Version <> '') and (Version <> '0.0.0.0'));
end;
