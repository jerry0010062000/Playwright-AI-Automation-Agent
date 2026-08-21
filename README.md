# Automated Sitemap Accessibility Control Center (ASACC)

ASACC 是一款結合 **Playwright 自動化爬蟲、網站地圖（Sitemap）樹狀拓撲，與多模態 AI（Gemini / Claude）視覺代理（Computer Use）** 的數位無障礙（WCAG 2.2 / Axe-core）自動化檢測控制台。

本系統專為現代單頁應用程式（SPA，例如路由器 RWD Web 後台）與傳統網頁設計，提供一鍵式的無障礙合規掃描、樹狀結構分析與詳細診斷報告。

---

## 🌟 核心特色

1. **AI 視覺與鍵盤焦點代理 (Dynamic AI Audit)**：
   - 整合 Gemini (2.5) 與 Claude (3.5/4.5) API 的電腦操作能力（Computer Use），模擬身心障礙者僅能以鍵盤防盲導航的點擊、輸入與焦點輪廓（Focus Ring）狀態，執行動態行為檢測。
2. **自動化網站地圖探索與重構 (Sitemap Hierarchy Restructuring)**：
   - 自動探索全站路由，並根據實體 URL 路徑層級**自動補齊中階虛擬目錄節點**（以 `📁` 資料夾標誌呈現），讓視覺化地圖具有深刻的深度與分支感。
3. **無障礙靜態掃描 (Local Axe-core Scan)**：
   - 整合本地自動化無障礙代碼檢測引擎（Axe-core），支援 WCAG 1.1 至 4.1 全量標準，提供 0-Token 消耗的高速檢測。
4. **一鍵式環境部署與容錯**：
   - 提供 `setup.bat` 腳本，具備 Windows `py` 啟動器 Fallback 機制，即使全域沒有設定 Python 環境變數 (PATH)，也能一鍵部署虛擬環境與下載 Playwright 瀏覽器二進位檔。
5. **GUI 配置自動保存與讀取**：
   - 所有的目標網址、測試模式、模擬裝置與帳密等配置皆與特定的 Sitemap JSON 檔綁定。切換地圖即自動載入設定，開箱即用。

---

## 📂 檔案目錄架構

```text
├── agent.py                            # CLI 檢測驅動核心與 Playwright 爬蟲主體
├── gui.py                              # Tkinter 視覺化控制台與即時 CMD 日誌視窗
├── prompts.py                          # 分層指令提示詞系統 v3.0 (IDENTITY, PROTOCOLS, SKILLS)
├── gemini_client.py                    # Gemini 多模態 API 客戶端與 Function Call 轉換
├── claude_client.py                    # Claude (Anthropic) API 客戶端
├── setup.bat                           # 一鍵環境安裝批次檔 (抗 Windows 括號與路徑 Bug 版)
├── run_gui.bat                         # 一鍵啟動 GUI 控制台批次檔
├── requirements.txt                    # Python 專案依賴包定義
├── Sitemap_Schema_Specification.md     # 網站地圖 JSON 欄位架構說明書
├── documentation/
│   ├── WCAG22_Specification.md         # WCAG 2.2 標準稽核指引文件
│   └── wcag_rules/                     # 各章節注入用無障礙細則 Markdown 庫
└── sitemaps/
    ├── test.json                       # 網站地圖檔案庫 (包含節點、狀態與配置)
    └── arc-prpl-map.json
```

---

## ⚙️ 環境安裝與部署 (Windows)

對於全新、乾淨的 Windows 電腦，請依循以下三個步驟：

1. **安裝 Python 3.10+**：
   - 前往 [Python 官網](https://www.python.org/downloads/) 下載安裝，**請務必勾選「Add python.exe to PATH」**。
2. **一鍵執行環境安裝**：
   - 雙擊執行目錄下的 **`setup.bat`**。
   - 它會自動建立虛擬環境 `.venv`、升級 pip、安裝 requirements.txt 中的庫，並下載 Playwright 的 Chrome/Firefox 驅動。

### 🛠️ 手動安裝方式 (CMD / PowerShell)
如果您希望使用指令手動完成設定，請在專案根目錄下依序執行：
1. **建立虛擬環境**：
   ```bash
   python -m venv .venv
   ```
2. **安裝 Python 依賴庫**：
   ```bash
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\pip.exe install -r requirements.txt
   ```
3. **下載並安裝 Playwright 瀏覽器內核**：
   ```bash
   .\.venv\Scripts\playwright.exe install
   ```

3. **填寫 API 金鑰**：
   - 在專案根目錄下，將 `config_llm.example.py` 複製並重新命名為 **`config_llm.py`**。
   - 用文字編輯器打開它，填入您的金鑰：
     ```python
     CLAUDE_API_KEY = "你的_Claude_API_Key"
     ```

---

## 🚀 使用指南

### 1. 啟動控制台
* 雙擊專案目錄下的 **`run_gui.bat`** 即可直接開啟 GUI 控制介面。

### 2. 建立或選擇地圖
* 於左側面板最上方選擇您要檢測的網站地圖（例如 `sitemaps/test.json`）。
* 若為全新專案，可選擇或建立新 JSON，系統會自動以 `/` 作為初始種子節點。

### 3. 選擇主要任務類別
* **探索與初始化網站地圖 (Explore & Initialize Sitemap)**：
  - 程式將自動登入目標網站，並循著同源連結爬行全站，自動生成完整的層級地圖與 `CATEGORY` 目錄，呈現在右側的「網站地圖樹狀圖」標籤頁中。
* **動態單頁無障礙檢測**：
  - 專門針對單一網頁進行動態 AI 稽核。您可以在 Treeview 節點上**按右鍵選擇「快速插入至 Page 欄位」**，再指定想稽核的 WCAG 細則。
* **靜態全站無障礙檢測**：
  - 使用 Axe-core 引擎快速掃描全站所有網頁，極速產出合規報表。

### 4. 監控與報告
* 按下 **`🚀 啟動檢測任務`** 後，介面會自動切換至「實時 CMD 終端」看見 AI 的思考與動作輸出（已強制限制 AI 於操作過程一律以**繁體中文**輸出 Thoughts 與 Actions 描述）。
* 掃描完成後，無障礙測試報告與 Token 消耗統計將被實時寫入對應的地圖檔中，並在 Treeview 節點狀態上更新（例如變更為綠色 `✅ 已靜態校對`、藍色 `🤖 已動態校對`）。

---

## 📝 開發者說明 (AI Reader Friendly)
* 本專案的 Sitemap JSON 設計極為嚴格，詳細欄位規範請參閱根目錄下的 [Sitemap_Schema_Specification.md](documentation/Sitemap_Schema_Specification.md)。
* 修改與新增任何 AI 操作邏輯時，請優先調整 [prompts.py](prompts.py) 以免破壞分層指令架構。
