; NSIS Installer for KN Graph
; Build with: makensis setup.nsi

Unicode true
Name "KN Graph"
OutFile "dist_exe\KN_Graph_Setup.exe"
InstallDir "$PROGRAMFILES\KN Graph"
InstallDirRegKey HKLM "Software\KN Graph" "InstallDir"
RequestExecutionLevel admin

; --- Pages ---
!include MUI2.nsh
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

; --- Installer ---
Section "Install"
    SetOutPath "$INSTDIR"

    ; Copy the main executable
    File "dist_exe\kn_graph.exe"

    ; Write uninstaller
    WriteUninstaller "$INSTDIR\Uninstall.exe"

    ; Registry for uninstall info
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KN Graph" "DisplayName" "KN Graph"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KN Graph" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KN Graph" "DisplayIcon" '"$INSTDIR\kn_graph.exe"'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KN Graph" "Publisher" "ScholarAI"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KN Graph" "DisplayVersion" "0.1.0"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KN Graph" "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KN Graph" "NoRepair" 1

    ; Store install dir
    WriteRegStr HKLM "Software\KN Graph" "InstallDir" "$INSTDIR"

    ; Start Menu shortcuts
    CreateDirectory "$SMPROGRAMS\KN Graph"
    CreateShortcut "$SMPROGRAMS\KN Graph\KN Graph.lnk" "$INSTDIR\kn_graph.exe" "serve" "$INSTDIR\kn_graph.exe" 0
    CreateShortcut "$SMPROGRAMS\KN Graph\Uninstall.lnk" "$INSTDIR\Uninstall.exe"

    ; Desktop shortcut
    CreateShortcut "$DESKTOP\KN Graph.lnk" "$INSTDIR\kn_graph.exe" "serve" "$INSTDIR\kn_graph.exe" 0
SectionEnd

; --- Uninstaller ---
Section "Uninstall"
    Delete "$INSTDIR\kn_graph.exe"
    Delete "$INSTDIR\Uninstall.exe"
    RMDir "$INSTDIR"

    Delete "$SMPROGRAMS\KN Graph\KN Graph.lnk"
    Delete "$SMPROGRAMS\KN Graph\Uninstall.lnk"
    RMDir "$SMPROGRAMS\KN Graph"

    Delete "$DESKTOP\KN Graph.lnk"

    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KN Graph"
    DeleteRegKey HKLM "Software\KN Graph"
SectionEnd
