; OCRing v1.0.0 Inno Setup script

#define MyAppName "OCRing"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "OCRing"
#define MyAppExeName "run_ocring.exe"
#define MyAppDataDir "E:\Ocring"

[Setup]
AppId={{7E47B4C0-79F0-4E19-9A7D-A52D0EE64C3B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=dist\installer
OutputBaseFilename=ocring-1.0.0-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "addtopath"; Description: "Add OCRing to PATH"; GroupDescription: "Optional tasks:"; Flags: unchecked

[Dirs]
Name: "{#MyAppDataDir}"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "run_ocring.py"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\OCRing"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\OCRing Profile Editor"; Filename: "{app}\{#MyAppExeName}"; Parameters: "profile-editor"
Name: "{autodesktop}\OCRing"; Filename: "{app}\{#MyAppExeName}"; Tasks: addtopath

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch OCRing"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsAddPath(Param: string): Boolean;
var
  Paths: string;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Paths) then
    Paths := '';
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(Paths) + ';') = 0;
end;
