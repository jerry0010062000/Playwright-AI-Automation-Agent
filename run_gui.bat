@echo off
:: 切換至該批次檔所在的目錄，確保路徑正確
cd /d "%~dp0"

:: 定義虛擬環境實際存放路徑
set "REAL_VENV=%USERPROFILE%\.venv_asacc"

:: 檢查虛擬環境中是否存在 pythonw.exe (優先使用實際短路徑以避免 Windows 長路徑限制)
if exist "%REAL_VENV%\Scripts\pythonw.exe" (
    start "" "%REAL_VENV%\Scripts\pythonw.exe" gui.py
) else if exist "%REAL_VENV%\Scripts\python.exe" (
    start "" "%REAL_VENV%\Scripts\python.exe" gui.py
) else if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" gui.py
) else if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" gui.py
) else (
    :: 嘗試使用全域的 pythonw，如果失敗則使用普通的 python
    start "" pythonw gui.py 2>nul || start "" python gui.py
)
