; Inno Setup script: installs Schalk to "C:\Program Files\Schalk" (needs administrator rights).
; Built by the release workflow:  iscc /DAppVersion=1.2 installer\schalk.iss
; User data lives in %LOCALAPPDATA%\Schalk and is neither installed nor removed by this setup.

#ifndef AppVersion
  #error AppVersion fehlt: iscc /DAppVersion=<Version> installer\schalk.iss
#endif

[Setup]
; Never change the AppId: it identifies the installation for updates and the uninstaller
AppId={{91D2360E-EABB-4592-B332-899AE49679CE}
AppName=Schalk
AppVersion={#AppVersion}
AppVerName=Schalk {#AppVersion}
AppPublisher=Niklas Theiler
AppPublisherURL=https://github.com/niklastheiler/Schalk
DefaultDirName={autopf}\Schalk
DefaultGroupName=Schalk
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Schalk-Setup-v{#AppVersion}
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\Schalk.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\src\resources\icons\schalk.ico
; A running Schalk is closed before its files are replaced
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Remove the files of the previous version so nothing outdated stays behind
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Schalk\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Schalk"; Filename: "{app}\Schalk.exe"
Name: "{group}\Schalk deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Schalk"; Filename: "{app}\Schalk.exe"; Tasks: desktopicon

[Run]
; Interactive installation: offer to start Schalk at the end
Filename: "{app}\Schalk.exe"; Description: "{cm:LaunchProgram,Schalk}"; Flags: nowait postinstall skipifsilent
; Silent update from within Schalk (/STARTAPP=1): start the new version afterwards
Filename: "{app}\Schalk.exe"; Flags: nowait; Check: StartAfterUpdate

[Code]
function StartAfterUpdate: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:STARTAPP|0}') = '1');
end;
