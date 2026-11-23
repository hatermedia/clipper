; Clipper native Windows installer (per-user, no admin)
Unicode true
!include "MUI2.nsh"

!define APPNAME "Clipper"
!define PUBLISHER "hatermedia"
!define APPEXE "Clipper.exe"
!define APPURL "https://github.com/hatermedia/clipper"

!ifndef VERSION
  !define VERSION "0.3.0"
!endif
!ifndef VI_VERSION
  !define VI_VERSION "0.3.0.0"
!endif

Name "${APPNAME} ${VERSION}"
OutFile "release\ClipperSetup-${VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\Clipper"
InstallDirRegKey HKCU "Software\Clipper" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64

Icon "icon.ico"
UninstallIcon "icon.ico"
VIProductVersion "${VI_VERSION}"
VIAddVersionKey "ProductName" "Clipper"
VIAddVersionKey "CompanyName" "${PUBLISHER}"
VIAddVersionKey "FileDescription" "Clipper native gameplay highlight trimmer"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "MIT licensed"

!define MUI_ABORTWARNING
!define MUI_ICON "icon.ico"
!define MUI_UNICON "icon.ico"
!define MUI_FINISHPAGE_RUN "$INSTDIR\Clipper.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch Clipper"

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Clipper" SecMain
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File /r "desktop-dist\Clipper\*.*"

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateShortCut "$SMPROGRAMS\Clipper.lnk" "$INSTDIR\${APPEXE}"
  CreateShortCut "$DESKTOP\Clipper.lnk" "$INSTDIR\${APPEXE}"

  WriteRegStr HKCU "Software\Clipper" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Clipper" "Version" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\App Paths\Clipper.exe" "" "$INSTDIR\${APPEXE}"

  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clipper" "DisplayName" "Clipper"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clipper" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clipper" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clipper" "DisplayIcon" "$INSTDIR\${APPEXE}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clipper" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clipper" "URLInfoAbout" "${APPURL}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clipper" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clipper" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clipper" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$DESKTOP\Clipper.lnk"
  Delete "$SMPROGRAMS\Clipper.lnk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clipper"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\App Paths\Clipper.exe"
  DeleteRegKey HKCU "Software\Clipper"
  RMDir /r "$INSTDIR"
SectionEnd
