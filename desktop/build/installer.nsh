; Custom NSIS steps for the GlobalBLOCS Quant Windows installation wizard (included by electron-builder).
!macro customInit
  ; Warn early if Python 3.10+ is missing; the first-run Setup Wizard can still guide the user.
  nsExec::ExecToStack 'py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"'
  Pop $0
  ${If} $0 != "0"
    MessageBox MB_ICONINFORMATION|MB_OK "GlobalBLOCS Quant needs Python 3.10 or newer for its analytics engine.$\r$\n$\r$\nSetup will continue. After installation, the Setup Wizard will help you install Python (python.org) before the engine is configured."
  ${EndIf}
!macroend

!macro customUnInstall
  MessageBox MB_YESNO|MB_ICONQUESTION "Also remove your GlobalBLOCS settings, encrypted credentials, audit log and engine environment?$\r$\n(Choose No to keep them for a future reinstall.)" IDNO keep
    RMDir /r "$APPDATA\GlobalBLOCS Quant"
  keep:
!macroend
