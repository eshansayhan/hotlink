; =====================================================================
; HFVideoPlatform - Profesyonel Windows Kurulum Sihirbazi (Inno Setup)
; Yazar: Eshan Sayhan
; Telif Hakki (C) 2026 Eshan Sayhan. Tum haklari saklidir.
; =====================================================================

#define MyAppName "HFVideoPlatform"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Eshan Sayhan"
#define MyAppURL "https://github.com/eshansayhan/hfstream"
#define MyAppExeName "HFVideoPlatform.exe"
#define MyPackExeName "PackManager.exe"

[Setup]
AppId={{5D9F2B8E-47C1-4D90-9A74-BFB6D97123A1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Seffaf ve Ozgur Kurulum: Kullanici diledigi klasore kurabilir
DefaultDirName={autopf}\{#MyAppName}
DisableDirPage=no
UsePreviousAppDir=yes
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=no

; Cikti ve Sıkıştırma Ayarlari
OutputDir=Output
OutputBaseFilename=HFVideoPlatform_Setup
SetupIconFile=..\assets\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Windows 10/11 Uyumlulugu
MinVersion=10.0

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "runatstartup"; Description: "Windows baslangicinda otomatik baslat (Saat tarafinda sessiz calisir)"; GroupDescription: "Baslangic Ayarlari:"; Flags: unchecked

[Files]
; Ana Calistirilabilir Dosyalar
Source: "..\HFVideoPlatform.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\PackManager.exe"; DestDir: "{app}"; Flags: ignoreversion

; Gerekli DLL ve Bagimliliklar
Source: "..\libcurl.dll"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\WebView2Loader.dll"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\glfw3.dll"; DestDir: "{app}"; Flags: ignoreversion

; Konfigurasyon ve Veri Dosyalari
Source: "..\hf_accounts.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\imgui.ini"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\master_index.json"; DestDir: "{app}"; Flags: ignoreversion

; Simgeler
Source: "..\assets\app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\PackManager (Paket Yoneticisi)"; Filename: "{app}\{#MyPackExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"; Tasks: desktopicon

[Registry]
; HFVideoPlatform Ayarlari (Regedit HKCU)
Root: HKCU; Subkey: "Software\{#MyAppName}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#MyAppName}"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#MyAppName}"; ValueType: dword; ValueName: "Port"; ValueData: 8080; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#MyAppName}"; ValueType: dword; ValueName: "MinimizeToTray"; ValueData: 1; Flags: uninsdeletekey

; Windows Baslangicinda Calistirma (Secildiyse)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"" --tray"; Tasks: runatstartup; Flags: uninsdeletevalue

[Run]
; Kurulum bittikten sonra calistirma secenegi
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
