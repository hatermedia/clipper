; Clipper native Windows installer (per-user, no admin)
Unicode true
!include "MUI2.nsh"

!define APPNAME "Clipper"
!define PUBLISHER "hatermedia"
!define APPEXE "Clipper.exe"
!define APPURL "https://github.com/hatermedia/clipper"
!define POWERSHELL "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe"

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
; Non-solid LZMA keeps upgrade installs responsive: each file can be extracted
; without first decompressing the whole 1 GB payload. Solid compression made
; the bundled Whisper model.bin look like it was hanging during install.
SetCompressor lzma
SetCompressorDictSize 64
SetOverwrite on

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

; No directory page: upgrades always reuse the existing install location.
; Allowing a second path is how two Clipper versions end up side by side.
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  ; Prefer the primary key, then the Windows uninstall entry. This catches
  ; installs written by older builds that may not have the primary key.
  ReadRegStr $0 HKCU "Software\Clipper" "InstallDir"
  StrCmp $0 "" 0 check_existing
  ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clipper" "InstallLocation"
check_existing:
  StrCmp $0 "" done
  IfFileExists "$0\Clipper.exe" 0 done
  StrCpy $INSTDIR $0
done:
FunctionEnd

!macro CloseClipperImpl PREFIX
  IfFileExists "$INSTDIR\close_clipper.ps1" ${PREFIX}_has_script
  Goto ${PREFIX}_try_taskkill

${PREFIX}_has_script:
  nsExec::ExecToStack '"${POWERSHELL}" -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "$INSTDIR\close_clipper.ps1"'
  Pop $0
  Pop $1
  StrCmp $0 "0" ${PREFIX}_close_done

${PREFIX}_try_taskkill:
  nsExec::ExecToStack '"$SYSDIR\taskkill.exe" /F /IM Clipper.exe /T'
  Pop $0
  Pop $1

${PREFIX}_close_done:
!macroend

Function CloseClipper
  !insertmacro CloseClipperImpl install
FunctionEnd

Function un.CloseClipper
  !insertmacro CloseClipperImpl uninstall
FunctionEnd

Section "Clipper" SecMain
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File "desktop-dist\Clipper\close_clipper.ps1"
  Call CloseClipper
  Sleep 1000
  ; Remove only known Clipper-owned files/directories, and only when this is
  ; an existing Clipper install. Never wipe a user-chosen install directory
  ; recursively.
  ReadRegStr $0 HKCU "Software\Clipper" "InstallDir"
  StrCmp $0 "$INSTDIR" 0 cleanup_done
  IfFileExists "$INSTDIR\Clipper.exe" cleanup_old
  IfFileExists "$INSTDIR\Uninstall.exe" cleanup_old
  Goto cleanup_done

cleanup_old:
  Delete "$INSTDIR\Clipper.exe"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\README.txt"
  Delete "$INSTDIR\BUILD_INFO.txt"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.txt"
  Delete "$INSTDIR\FFMPEG_NOTICE.txt"
  Delete "$INSTDIR\COPYING.GPLv3.txt"
  Delete "$INSTDIR\close_clipper.ps1"
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\bin"
  RMDir /r "$INSTDIR\licenses"

cleanup_done:
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
  Call un.CloseClipper
  Sleep 1000
  Delete "$DESKTOP\Clipper.lnk"
  Delete "$SMPROGRAMS\Clipper.lnk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clipper"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\App Paths\Clipper.exe"
  DeleteRegKey HKCU "Software\Clipper"
  DeleteRegKey HKCU "Software\hatermedia\Clipper"
  DeleteRegKey /ifempty HKCU "Software\hatermedia"
  Delete "$INSTDIR\Clipper.exe"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\README.txt"
  Delete "$INSTDIR\BUILD_INFO.txt"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.txt"
  Delete "$INSTDIR\FFMPEG_NOTICE.txt"
  Delete "$INSTDIR\COPYING.GPLv3.txt"
  Delete "$INSTDIR\close_clipper.ps1"
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\bin"
  RMDir /r "$INSTDIR\licenses"
  RMDir "$INSTDIR"
SectionEnd
