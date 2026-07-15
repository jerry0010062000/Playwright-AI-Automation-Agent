"""
配置檔案
定義程式的全域配置參數
"""

import os

# ========================================
# API Key 配置
# ========================================

# Gemini API Key
# 建議使用環境變數 GEMINI_API_KEY，或建立不提交的 config_local.py 覆蓋此值。
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", os.getenv("ANTHROPIC_API_KEY", "")).strip()
CLAUDE_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "").strip()
CLAUDE_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()
CLAUDE_DISABLE_EXPERIMENTAL_BETAS = os.getenv("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", "").strip()
CLAUDE_USE_GATEWAY = os.getenv("CLAUDE_USE_GATEWAY", "False").strip().lower() in ("true", "1")

try:
    from config_local import GEMINI_API_KEY as LOCAL_GEMINI_API_KEY
    if LOCAL_GEMINI_API_KEY:
        GEMINI_API_KEY = LOCAL_GEMINI_API_KEY.strip()
except ImportError:
    pass

try:
    from config_local import CLAUDE_API_KEY as LOCAL_CLAUDE_API_KEY
    if LOCAL_CLAUDE_API_KEY:
        CLAUDE_API_KEY = LOCAL_CLAUDE_API_KEY.strip()
except ImportError:
    pass

try:
    from config_local import CLAUDE_BASE_URL as LOCAL_CLAUDE_BASE_URL
    if LOCAL_CLAUDE_BASE_URL:
        CLAUDE_BASE_URL = LOCAL_CLAUDE_BASE_URL.strip()
except ImportError:
    pass

try:
    from config_local import CLAUDE_AUTH_TOKEN as LOCAL_CLAUDE_AUTH_TOKEN
    if LOCAL_CLAUDE_AUTH_TOKEN:
        CLAUDE_AUTH_TOKEN = LOCAL_CLAUDE_AUTH_TOKEN.strip()
except ImportError:
    pass

try:
    from config_local import CLAUDE_DISABLE_EXPERIMENTAL_BETAS as LOCAL_CLAUDE_DISABLE
    if LOCAL_CLAUDE_DISABLE:
        CLAUDE_DISABLE_EXPERIMENTAL_BETAS = LOCAL_CLAUDE_DISABLE.strip()
except ImportError:
    pass

try:
    from config_local import CLAUDE_USE_GATEWAY as LOCAL_CLAUDE_USE_GATEWAY
    if LOCAL_CLAUDE_USE_GATEWAY is not None:
        if isinstance(LOCAL_CLAUDE_USE_GATEWAY, str):
            CLAUDE_USE_GATEWAY = LOCAL_CLAUDE_USE_GATEWAY.strip().lower() in ("true", "1")
        else:
            CLAUDE_USE_GATEWAY = bool(LOCAL_CLAUDE_USE_GATEWAY)
except ImportError:
    pass

CLAUDE_COMPUTER_TOOL_TYPE = os.getenv("CLAUDE_COMPUTER_TOOL_TYPE", "computer_20251124").strip()
CLAUDE_COMPUTER_BETAS = os.getenv("CLAUDE_COMPUTER_BETAS", "computer-use-2025-11-24").strip()

try:
    from config_local import CLAUDE_COMPUTER_TOOL_TYPE as LOCAL_TOOL_TYPE
    if LOCAL_TOOL_TYPE:
        CLAUDE_COMPUTER_TOOL_TYPE = LOCAL_TOOL_TYPE.strip()
except ImportError:
    pass

try:
    from config_local import CLAUDE_COMPUTER_BETAS as LOCAL_BETAS
    if LOCAL_BETAS:
        CLAUDE_COMPUTER_BETAS = LOCAL_BETAS.strip()
except ImportError:
    pass


# ========================================
# 自動登入配置
# ========================================
AUTO_LOGIN_USERNAME = os.getenv("AUTO_LOGIN_USERNAME", "").strip()
AUTO_LOGIN_PASSWORD = os.getenv("AUTO_LOGIN_PASSWORD", "").strip()

try:
    from config_local import AUTO_LOGIN_USERNAME as LOCAL_AUTO_LOGIN_USERNAME
    if LOCAL_AUTO_LOGIN_USERNAME:
        AUTO_LOGIN_USERNAME = LOCAL_AUTO_LOGIN_USERNAME.strip()
except ImportError:
    pass

try:
    from config_local import AUTO_LOGIN_PASSWORD as LOCAL_AUTO_LOGIN_PASSWORD
    if LOCAL_AUTO_LOGIN_PASSWORD:
        AUTO_LOGIN_PASSWORD = LOCAL_AUTO_LOGIN_PASSWORD.strip()
except ImportError:
    pass




# 瀏覽器配置
# ========================================

# 瀏覽器視窗大小設定
SCREEN_WIDTH = 1440
SCREEN_HEIGHT = 900

# 是否顯示瀏覽器視窗（False = 有視窗，True = 無頭模式）
HEADLESS = False


# ========================================
# AI 代理配置
# ========================================

# AI 模型名稱（預設值，可透過命令列參數覆蓋）
MODEL_NAME = 'gemini-2.5-computer-use-preview-10-2025'
#  MODEL_NAME = 'gemini-3.5'

# Gemini API 工具類型
TOOL_TYPE = "computer_use"

# 工具環境
TOOL_ENVIRONMENT = "browser"

# 預設任務（當命令列沒有指定時使用）
DEFAULT_TASK = "到目標頁面中,用中文告訴我看到了甚麼 點擊任意可互動元素 然後結束操作"

# 初始 HTTP 路徑（啟動時的起始頁面）
INITIAL_URL = "http://localhost:8000"

# AI 代理的最大執行回合數（避免無限循環）
MAX_TURNS = 100

# 是否啟用提示注入偵測（安全性功能）
ENABLE_PROMPT_INJECTION_DETECTION = True


# ========================================
# AI 行為配置（prompts.py 使用）
# ========================================

# AI 角色類型
# 可選值：default, tester, scraper, shopper, researcher
AI_ROLE = "default"

# AI 行為模式
# 可選值：careful（謹慎）, fast（快速）, verbose（詳細）, silent（靜默）
AI_BEHAVIOR = "careful"

# 輸出格式
# 可選值：natural（自然語言）, json, list, table
OUTPUT_FORMAT = "natural"

# 是否包含特殊情境處理指引
INCLUDE_SITUATION_HANDLERS = True

# 是否使用完整提示詞（False = 使用簡單提示詞）
USE_FULL_PROMPT = True

# 排除的預定義功能（選填，用於限制 AI 操作）
# 例如：["drag_and_drop"]
EXCLUDED_PREDEFINED_FUNCTIONS = ["drag_and_drop"]



# ========================================
# 執行配置
# ========================================

# 每次操作後的等待時間（秒）
ACTION_DELAY = 0.5

# 頁面載入超時時間（毫秒）
PAGE_LOAD_TIMEOUT = 5000

# 點擊輸入框後等待焦點的時間（秒）
INPUT_FOCUS_DELAY = 0.3

# 任務完成後觀察結果的時間（秒）
RESULT_OBSERVATION_TIME = 1

# 爬蟲最大巡檢頁數（全站靜態巡檢時使用）
MAX_CRAWL_PAGES = 100

# AI 預先登入嘗試最大回合數
MAX_LOGIN_TURNS = 10


# ========================================
# 載入進階參數設定 (非敏感資料，可納入遠端 Git 庫)
# ========================================
CONFIG_ADVANCED_PATH = os.path.join(os.path.dirname(__file__), "config_advanced.json")

if os.path.exists(CONFIG_ADVANCED_PATH):
    try:
        with open(CONFIG_ADVANCED_PATH, "r", encoding="utf-8") as f:
            adv_config = json.load(f)
        if "MAX_CRAWL_PAGES" in adv_config:
            MAX_CRAWL_PAGES = int(adv_config["MAX_CRAWL_PAGES"])
        if "MAX_LOGIN_TURNS" in adv_config:
            MAX_LOGIN_TURNS = int(adv_config["MAX_LOGIN_TURNS"])
        if "RESULT_OBSERVATION_TIME" in adv_config:
            RESULT_OBSERVATION_TIME = int(adv_config["RESULT_OBSERVATION_TIME"])
        if "ACTION_DELAY" in adv_config:
            ACTION_DELAY = float(adv_config["ACTION_DELAY"])
        if "PAGE_LOAD_TIMEOUT" in adv_config:
            PAGE_LOAD_TIMEOUT = int(adv_config["PAGE_LOAD_TIMEOUT"])
    except Exception as e:
        print(f"[WARNING] 載入 config_advanced.json 失敗: {e}")
