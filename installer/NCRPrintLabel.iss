; NCR Print Label - Inno Setup 6 script.
; Built by scripts\build.ps1, which passes /DAppVersion=<x.y.z>.
; Installs the PyInstaller folder dist\NCRPrintLabel (no Python needed on the PC).
; Renamed from "NCR QR Label Printer": AppId, AppMutex and the user data folder are unchanged,
; so installing over the old version upgrades it and keeps settings and history.
; User data (settings, history, logs) lives in %LOCALAPPDATA%\NCR\QRLabelPrinter and is kept on upgrade.
; Does NOT install printer drivers, ODBC drivers, change firewall rules or grant database rights.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "NCR Print Label"
#define AppExe "NCRPrintLabel.exe"

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
DefaultDirName={autopf}\NCR Print Label
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=NCR-Print-Label-Setup-{#AppVersion}
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
; Parts of the program (written to install-options.json, read by the app on start).
; Silent install: /TASKS="modasset,modjournal" (add desktopicon for a desktop shortcut).
Name: "modasset"; Description: "Asset labels (fixed assets)"; GroupDescription: "Use the program for:"
Name: "modjournal"; Description: "Stock labels (inventory transfer journal)"; GroupDescription: "Use the program for:"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[UninstallDelete]
Type: files; Name: "{app}\install-options.json"

[InstallDelete]
; Remove files of the previous version so old libraries do not stay behind.
Type: filesandordirs; Name: "{app}\_internal"
; files of the old name "NCR QR Label Printer"
Type: files; Name: "{app}\NCRQRLabelPrinter.exe"
Type: files; Name: "{autoprograms}\NCR QR Label Printer.lnk"
Type: files; Name: "{autodesktop}\NCR QR Label Printer.lnk"

[Files]
Source: "..\dist\NCRPrintLabel\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; Automatic update from the program (silent install with /RELAUNCH=1): start it again afterwards.
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: RelaunchRequested

[Code]
function RelaunchRequested: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectTasks) and (not WizardIsTaskSelected('modasset')) and
     (not WizardIsTaskSelected('modjournal')) then
  begin
    MsgBox('Choose at least one part: Asset labels or Stock labels.', mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Modules: String;
begin
  if CurStep = ssPostInstall then
  begin
    Modules := '';
    if WizardIsTaskSelected('modasset') then
      Modules := '"asset"';
    if WizardIsTaskSelected('modjournal') then
    begin
      if Modules <> '' then
        Modules := Modules + ', ';
      Modules := Modules + '"journal"';
    end;
    if Modules = '' then
      Modules := '"asset", "journal"';
    SaveStringToFile(ExpandConstant('{app}\install-options.json'),
      '{"modules": [' + Modules + ']}' + #13#10, False);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataPath: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataPath := ExpandConstant('{localappdata}\NCR\QRLabelPrinter');
    if DirExists(DataPath) and (not UninstallSilent) then
    begin
      if MsgBox('Also delete the settings, print history and logs of NCR Print Label?' + #13#10#13#10 +
                DataPath + #13#10#13#10 +
                'Choose No to keep them (for example when reinstalling).',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataPath, True, True, True);
    end;
  end;
end;
