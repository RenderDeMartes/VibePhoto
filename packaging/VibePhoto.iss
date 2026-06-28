; Inno Setup script for the Vibe Photo Windows installer.
;
; Packages the PyInstaller one-folder bundle (dist\VibePhoto\) into a single
; setup executable: dist\VibePhoto-Setup-<version>.exe.
;
; Build the whole chain with:  python scripts\build_installer.py
; (that runs PyInstaller, then invokes the Inno Setup compiler, ISCC.exe).
; Install Inno Setup 6 first: https://jrsoftware.org/isdl.php

#define MyAppName "Vibe Photo"
#define MyAppPublisher "Vibe Photo"
#define MyAppExeName "VibePhoto.exe"
#define MyAppURL "https://github.com/RenderDeMartes/VibePhoto"

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

[Setup]
; A stable AppId keeps upgrades/uninstalls consistent across versions.
AppId={{8E5D6F2A-3C4B-4A1E-9F7D-2B6C1A9E4F30}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
; Output a single, fixed-name installer in the repo root (overwrites the old one).
OutputDir=..
OutputBaseFilename=VibePhoto-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Install per-user by default so no admin rights are required.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The entire PyInstaller bundle.
Source: "..\dist\VibePhoto\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
