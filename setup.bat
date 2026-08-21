@echo off
chcp 65001 >nul
set "VIRTUAL_ENV="
set "PYTHONHOME="
set "PYTHONPATH="
echo ==========================================
echo 🛡️ Playwright WCAG Accessibility Agent 環境安裝與設定
echo ==========================================
echo.

:: 檢查 Python 是否安裝
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
    goto python_ok
)

py --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py
    echo [提示] 偵測到系統中存在 Python 啟動器 (py)，將使用 py 指令建立虛擬環境。
    goto python_ok
)

echo [錯誤] 系統未安裝 Python 或未將其加入環境變數 (PATH)！
echo 請前往官網下載並安裝 Python 3.10 以上版本，並勾選 "Add Python to PATH"。
echo.
pause
exit /b 1

:python_ok

:: 決定虛擬環境實際存放路徑以避免 Windows 路徑太長問題
set "REAL_VENV=%USERPROFILE%\.venv_asacc"

:: 刪除舊的本地 .venv，避免目錄連接衝突
if exist ".venv" (
    echo [*] 正在清除專案目錄下舊的 .venv...
    rmdir /s /q ".venv"
)

:: 建立實際虛擬環境
if not exist "%REAL_VENV%" (
    echo [*] 正在建立虛擬環境於 %REAL_VENV%...
    %PYTHON_CMD% -m venv "%REAL_VENV%"
    if %errorlevel% neq 0 (
        echo [錯誤] 建立虛擬環境失敗！
        pause
        exit /b 1
    )
    echo [✓] 虛擬環境建立成功！
) else (
    echo [✓] 已偵測到現有的虛擬環境 %REAL_VENV%
)

:: 升級 pip 並安裝依賴套件
echo.
echo [*] 正在更新 pip 並自 requirements.txt 安裝依賴庫...
"%REAL_VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%REAL_VENV%\Scripts\python.exe" -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [錯誤] 安裝 Python 依賴庫失敗！
    pause
    exit /b 1
)
echo [✓] Python 套件安裝完成！

:: 安裝 Playwright 瀏覽器二進位檔
echo.
echo [*] 正在安裝 Playwright 瀏覽器二進位檔 (Chromium/Firefox/WebKit)...
"%REAL_VENV%\Scripts\python.exe" -m playwright install
if %errorlevel% neq 0 (
    echo [錯誤] 安裝 Playwright 瀏覽器失敗！
    pause
    exit /b 1
)
echo [✓] Playwright 瀏覽器安裝完成！

:: 建立目錄連接 (Junction) .venv -> %REAL_VENV%
echo.
echo [*] 正在建立 .venv 目錄連接...
mklink /j ".venv" "%REAL_VENV%"
if %errorlevel% neq 0 (
    echo [警告] 建立目錄連接失敗！將直接在本地建立虛擬環境與安裝...
    %PYTHON_CMD% -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe -m playwright install
    if %errorlevel% neq 0 (
        echo [錯誤] 建立與安裝本地虛擬環境失敗！
        pause
        exit /b 1
    )
) else (
    echo [✓] .venv 目錄連接建立成功！
)

echo.
echo ==========================================
echo 🎉 [成功] 環境設定完成！
echo 您現在可以雙擊 "run_gui.bat" 啟動無障礙 Agent 控制台。
echo ==========================================
echo.
pause
