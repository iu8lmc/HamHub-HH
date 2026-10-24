; Installer di HH - client HamHub Log per Decodium / DecoDXLog

#define MyAppName "HH - HamHub Log"
#define MyAppVersion "1.2.0"
#define MyAppExe "HH.exe"

[Setup]
AppId={{6F2B8E1A-3C4D-4E5F-9A0B-1C2D3E4F5A6B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=HamHub.cloud
AppPublisherURL=https://hamhub.cloud/log/
DefaultDirName={autopf}\HamHub\HH
DefaultGroupName=HamHub
DisableProgramGroupPage=yes
OutputDir=..\installer-out
OutputBaseFilename=HH-Setup
SetupIconFile=..\hh.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "autostart"; Description: "Avvia HH con Windows (consigliato: resta nell'area di notifica vicino all'orologio)"; GroupDescription: "Avvio:"
Name: "desktopicon"; Description: "Crea un'icona sul desktop"; GroupDescription: "Icone:"; Flags: unchecked

[Files]
Source: "..\HH.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\hh.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\HH - HamHub Log"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\hh.ico"
Name: "{group}\Configura HH"; Filename: "{app}\{#MyAppExe}"; Parameters: "--setup"; IconFilename: "{app}\hh.ico"
Name: "{group}\Disinstalla HH"; Filename: "{uninstallexe}"
Name: "{autodesktop}\HH - HamHub Log"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\hh.ico"; Tasks: desktopicon

[Registry]
; avvio con Windows: HH parte nell'area di notifica, senza finestre
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "HamHubHH"; ValueData: """{app}\{#MyAppExe}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
; la prima volta HH apre da solo la finestra per inserire la chiave di invio
Filename: "{app}\{#MyAppExe}"; Description: "Avvia HH adesso"; Flags: postinstall nowait skipifsilent

[Code]
// HH vive nell'area di notifica e non ha finestre da chiudere: prima di aggiornare o disinstallare si ferma la copia in esecuzione
procedure StopHH();
var
  R: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#MyAppExe}', '', SW_HIDE, ewWaitUntilTerminated, R);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopHH();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopHH();
end;
