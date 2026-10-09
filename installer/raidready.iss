; RaidReady installer. Wraps the same app-plus-Python folder the zip ships, but
; installed with a Start Menu shortcut and an uninstaller. Installed per-user
; (no admin) into a writable folder, so the in-app updater keeps working.
; Build:  ISCC /DMyAppVersion=1.5.0 installer\raidready.iss  ->  dist\RaidReadySetup.exe

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{9DB4174C-60B1-40BE-BFAD-9D4D9A61F640}
AppName=RaidReady
AppVersion={#MyAppVersion}
AppVerName=RaidReady {#MyAppVersion}
AppPublisher=RaidReady
AppPublisherURL=https://github.com/Grat6969/EFT-amd-control
DefaultDirName={localappdata}\Programs\RaidReady
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=RaidReadySetup
SetupIconFile=installer\raidready.ico
UninstallDisplayName=RaidReady
UninstallDisplayIcon={app}\raidready.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "dist\RaidReady\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Icons]
Name: "{autoprograms}\RaidReady"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m tarkov_display"; WorkingDir: "{app}"; IconFilename: "{app}\raidready.ico"
Name: "{autodesktop}\RaidReady"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m tarkov_display"; WorkingDir: "{app}"; IconFilename: "{app}\raidready.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-m tarkov_display"; WorkingDir: "{app}"; Description: "Start RaidReady now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
