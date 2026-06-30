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
