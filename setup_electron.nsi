; NSIS Installer for Scholar Wiki (Electron + Backend)
; Build with: makensis setup_electron.nsi

Unicode true
Name "Scholar Wiki"
OutFile "dist_exe\ScholarWiki_Setup.exe"
InstallDir "$PROGRAMFILES\ScholarWiki"
InstallDirRegKey HKLM "Software\ScholarWiki" "InstallDir"
RequestExecutionLevel admin
BrandingText "Scholar Wiki"

!include MUI2.nsh

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

Section "Install"
    SetOutPath "$INSTDIR"

    File /r "scholarai-workbench\dist-electron-pkg\ScholarWiki-win32-x64\*"

    WriteUninstaller "$INSTDIR\Uninstall.exe"

    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ScholarWiki" "DisplayName" "Scholar Wiki"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ScholarWiki" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ScholarWiki" "DisplayIcon" '"$INSTDIR\ScholarWiki.exe"'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ScholarWiki" "Publisher" "Scholar Wiki"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ScholarWiki" "DisplayVersion" "0.1.0"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ScholarWiki" "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ScholarWiki" "NoRepair" 1
    WriteRegStr HKLM "Software\ScholarWiki" "InstallDir" "$INSTDIR"

    CreateDirectory "$SMPROGRAMS\ScholarWiki"
    CreateShortcut "$SMPROGRAMS\ScholarWiki\Scholar Wiki.lnk" "$INSTDIR\ScholarWiki.exe" "" "$INSTDIR\ScholarWiki.exe" 0
    CreateShortcut "$SMPROGRAMS\ScholarWiki\Uninstall.lnk" "$INSTDIR\Uninstall.exe"

    CreateShortcut "$DESKTOP\Scholar Wiki.lnk" "$INSTDIR\ScholarWiki.exe" "" "$INSTDIR\ScholarWiki.exe" 0
SectionEnd

Section "Uninstall"
    Delete "$INSTDIR\ScholarWiki.exe"
    Delete "$INSTDIR\Uninstall.exe"
    RMDir /r "$INSTDIR\locales"
    RMDir /r "$INSTDIR\resources"
    Delete "$INSTDIR\*.*"
    RMDir "$INSTDIR"

    Delete "$SMPROGRAMS\ScholarWiki\Scholar Wiki.lnk"
    Delete "$SMPROGRAMS\ScholarWiki\Uninstall.lnk"
    RMDir "$SMPROGRAMS\ScholarWiki"

    Delete "$DESKTOP\Scholar Wiki.lnk"

    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ScholarWiki"
    DeleteRegKey HKLM "Software\ScholarWiki"
SectionEnd
