@echo off
chcp 65001 >nul
echo ==========================================
echo 🛡️ Playwright WCAG Accessibility Agent 環境安裝與設定
echo ==========================================
echo.

:: 檢查 Python 是否安裝
set PYTHON_CMD=python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% equ 0 (
        set PYTHON_CMD=py
        echo [提示] 偵測到系統中存在 Python 啟動器 (py)，將使用 py 指令建立虛擬環境。
    ) else (
        echo [錯誤] 系統未安裝 Python 或未將其加入環境變數 (PATH)！
        echo 請前往官網下載並安裝 Python 3.10 以上版本，並勾選 "Add Python to PATH"。
        echo.
        pause
        exit /b 1
    )
)

:: 建立虛擬環境 .venv
if not exist ".venv" (
    echo [*] 正在建立虛擬環境 (.venv)...
    %PYTHON_CMD% -m venv .venv
    if %errorlevel% neq 0 (
        echo [錯誤] 建立虛擬環境失敗！
        pause
        exit /b 1
    )
    echo [✓] 虛擬環境建立成功！
) else (
    echo [✓] 已偵測到現有的虛擬環境 (.venv)
)

:: 升級 pip 並安裝依賴套件
echo.
echo [*] 正在更新 pip 並自 requirements.txt 安裝依賴庫...
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt
if %errorlevel% neq 0 (
    echo [錯誤] 安裝 Python 依賴庫失敗！
    pause
    exit /b 1
)
echo [✓] Python 套件安裝完成！

:: 安裝 Playwright 瀏覽器二進位檔
echo.
echo [*] 正在安裝 Playwright 瀏覽器二進位檔 (Chromium/Firefox/WebKit)...
.\.venv\Scripts\playwright.exe install
if %errorlevel% neq 0 (
    echo [錯誤] 安裝 Playwright 瀏覽器失敗！
    pause
    exit /b 1
)
echo [✓] Playwright 瀏覽器安裝完成！

echo.
echo ==========================================
echo 🎉 [成功] 環境設定完成！
echo 您現在可以雙擊 "run_gui.bat" 啟動無障礙 Agent 控制台。
echo ==========================================
echo.
pause
