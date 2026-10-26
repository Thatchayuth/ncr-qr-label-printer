; NCR QR Label Printer - Inno Setup 6 script.
; Built by scripts\build.ps1, which passes /DAppVersion=<x.y.z>.
; Installs the PyInstaller folder dist\NCRQRLabelPrinter (no Python needed on the PC).
; User data (settings, history, logs) lives in %LOCALAPPDATA%\NCR\QRLabelPrinter and is kept on upgrade.
; Does NOT install printer drivers, ODBC drivers, change firewall rules or grant database rights.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "NCR QR Label Printer"
#define AppExe "NCRQRLabelPrinter.exe"

[Setup]
AppId={{9B2F6C1E-4A57-4C2B-9E7D-3F1A2B5C8D40}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=NCR
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
; Per-user install by default (no admin rights needed); the user may choose "install for all users".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\NCR QR Label Printer
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=NCR-QR-Label-Printer-Setup-{#AppVersion}
SetupIconFile=..\src\qrlabel\resources\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Ask to close a running copy (the app creates this mutex).
AppMutex=NCRQRLabelPrinter
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Remove files of the previous version so old libraries do not stay behind.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\NCRQRLabelPrinter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataPath: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataPath := ExpandConstant('{localappdata}\NCR\QRLabelPrinter');
    if DirExists(DataPath) and (not UninstallSilent) then
    begin
      if MsgBox('Also delete the settings, print history and logs of NCR QR Label Printer?' + #13#10#13#10 +
                DataPath + #13#10#13#10 +
                'Choose No to keep them (for example when reinstalling).',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataPath, True, True, True);
    end;
  end;
end;
