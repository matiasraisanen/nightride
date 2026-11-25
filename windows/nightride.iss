; Inno Setup script for the Windows installer, dist\nightride-setup.exe. It installs the program
; build.ps1 made in dist\nightride. build.ps1 runs this when Inno Setup 6 is installed:
;     ISCC /DAppVersion=2.0.0 windows\nightride.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Identifies the program to Windows across versions, so a new version replaces the old. Never change it.
AppId={{1D603891-D214-4D59-891E-4949C902D121}
AppName=Nightride player
AppVersion={#AppVersion}
AppPublisher=matiasraisanen
AppPublisherURL=https://github.com/matiasraisanen/nightride
AppSupportURL=https://github.com/matiasraisanen/nightride/issues
DefaultDirName={autopf}\Nightride
DisableProgramGroupPage=yes
; For the current user, so no administrator rights are needed. Administrators can choose all users.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; The program and its VLC are 64-bit
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=nightride-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\nightride.exe
SetupIconFile=nightride.ico

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\nightride\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Files of an older version that the new one doesn't have, like VLC plugins left out since
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
; nightride.exe is a terminal program, so Windows opens it in the terminal: Windows Terminal on
; Windows 11, the console window on Windows 10
Name: "{autoprograms}\Nightride player"; Filename: "{app}\nightride.exe"
Name: "{autodesktop}\Nightride player"; Filename: "{app}\nightride.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\nightride.exe"; Description: "{cm:LaunchProgram,Nightride player}"; Flags: nowait postinstall skipifsilent
