"""
Gemini + Playwright 自動化代理程式
使用 Google Gemini 的 Computer Use API 來自動操作瀏覽器

使用方法：
  基本：python agent.py "你的任務"
  進階：python agent.py -m gemini-2.0-flash-exp -r tester "任務"
  幫助：python agent.py --help
"""

import sys
import time
import argparse
import os
import datetime
import json
import re
from playwright.sync_api import sync_playwright

# 解決 Windows 主控台編碼問題，確保能正確輸出 UTF-8 字元
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


from config import (
    GEMINI_API_KEY, CLAUDE_API_KEY,
    SCREEN_WIDTH, SCREEN_HEIGHT, MAX_TURNS, HEADLESS,
    RESULT_OBSERVATION_TIME, MODEL_NAME, DEFAULT_TASK,
    INITIAL_URL, AI_ROLE, AI_BEHAVIOR, OUTPUT_FORMAT,
    TOOL_TYPE, TOOL_ENVIRONMENT, ENABLE_PROMPT_INJECTION_DETECTION,
    MAX_CRAWL_PAGES, MAX_LOGIN_TURNS
)
from gemini_client import GeminiAgent, get_function_responses
from claude_client import ClaudeAgent
from browser_actions import execute_function_calls, run_axe_audit, scan_focus_path


class NullWriter:
    """一個不進行任何寫入操作的虛擬 Writer，用於當不啟用 record 時代替檔案寫入"""
    def write(self, *args, **kwargs):
        pass
    def flush(self, *args, **kwargs):
        pass
    def close(self, *args, **kwargs):
        pass
    @property
    def closed(self):
        return True



def print_token_and_cost_summary(model_name: str, input_tokens: int, output_tokens: int, report_target=None):
    """
    計算並列印 Token 消耗與花費統計，支援寫入檔案或附加至列表
    """
    total_tokens = input_tokens + output_tokens
    
    PRICING = {
        # Fable & Mythos
        "claude-fable-5": {"input": 10.0, "output": 50.0},
        "claude-mythos-5": {"input": 10.0, "output": 50.0},
        # Opus
        "claude-opus-4.8": {"input": 5.0, "output": 25.0},
        "claude-opus-4.7": {"input": 5.0, "output": 25.0},
        "claude-opus-4.6": {"input": 5.0, "output": 25.0},
        "claude-opus-4.5": {"input": 5.0, "output": 25.0},
        "claude-opus-4.1": {"input": 15.0, "output": 75.0},
        "claude-opus-4": {"input": 15.0, "output": 75.0},
        "claude-3-opus": {"input": 15.0, "output": 75.0},
        # Sonnet
        "claude-sonnet-5": {"input": 3.0, "output": 15.0},
        "claude-sonnet-4.6": {"input": 3.0, "output": 15.0},
        "claude-sonnet-4.5": {"input": 3.0, "output": 15.0},
        "claude-sonnet-4": {"input": 3.0, "output": 15.0},
        "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
        # Haiku
        "claude-haiku-4.5": {"input": 1.0, "output": 5.0},
        "claude-haiku-3.5": {"input": 0.8, "output": 4.0},
        "claude-3-5-haiku": {"input": 0.8, "output": 4.0},
        # Gemini
        "gemini-2.5-computer-use": {"input": 1.25, "output": 5.0},
        "gemini-2.5-pro": {"input": 1.25, "output": 5.0},
        "gemini-2.5-flash": {"input": 0.075, "output": 0.3},
    }
    
    model_name_norm = model_name.lower().replace("-", ".").replace("_", ".")
    model_key = None
    
    # 進行標準化模糊比對
    for key in PRICING:
        key_norm = key.replace("-", ".").replace("_", ".")
        if key_norm in model_name_norm or model_name_norm in key_norm:
            model_key = key
            break
            
    # 概略 fallback 比對
    if not model_key:
        if "opus" in model_name_norm:
            model_key = "claude-3-opus"
        elif "haiku" in model_name_norm:
            model_key = "claude-3-5-haiku"
        elif "fable" in model_name_norm:
            model_key = "claude-fable-5"
        elif "mythos" in model_name_norm:
            model_key = "claude-mythos-5"
        elif "gemini" in model_name_norm:
            if "flash" in model_name_norm:
                model_key = "gemini-2.5-flash"
            else:
                model_key = "gemini-2.5-pro"
        else:
            model_key = "claude-3-5-sonnet"
            
    rates = PRICING[model_key]
    usd_input_cost = (input_tokens / 1000000.0) * rates["input"]
    usd_output_cost = (output_tokens / 1000000.0) * rates["output"]
    total_usd_cost = usd_input_cost + usd_output_cost
    
    EXCHANGE_RATE_TWD = 32.5
    total_twd_cost = total_usd_cost * EXCHANGE_RATE_TWD
    
    token_summary = (
        f"\n{'='*60}\n"
        f"💰 Token 消耗與花費統計 (Token Usage & Cost Summary)\n"
        f"{'='*60}\n"
        f"  輸入 Token (Input Tokens)  : {input_tokens:,}\n"
        f"  輸出 Token (Output Tokens) : {output_tokens:,}\n"
        f"  總計 Token (Total Tokens)  : {total_tokens:,}\n"
        f"{'-'*60}\n"
        f"  計費模型 (Pricing Model)   : {model_key} (輸入: ${rates['input']:.2f}/M, 輸出: ${rates['output']:.2f}/M)\n"
        f"  預估花費 (Estimated Cost)  : ${total_usd_cost:.5f} USD\n"
        f"  折合台幣 (Converted Cost)  : NT$ {total_twd_cost:.3f} TWD (匯率: {EXCHANGE_RATE_TWD})\n"
        f"{'='*60}\n"
    )
    print(token_summary)
    
    if report_target is not None:
        report_text = (
            f"## 💰 Token 消耗與花費統計\n\n"
            f"- **輸入 Token 數 (Input Tokens)**: `{input_tokens:,}`\n"
            f"- **輸出 Token 數 (Output Tokens)**: `{output_tokens:,}`\n"
            f"- **總計 Token 數 (Total Tokens)**: `{total_tokens:,}`\n"
            f"- **計費模型 (Pricing Model)**: `{model_key}` (輸入: ${rates['input']:.2f}/M, 輸出: ${rates['output']:.2f}/M)\n"
            f"- **預估美金花費 (Estimated USD)**: `${total_usd_cost:.5f} USD`\n"
            f"- **預估台幣花費 (Estimated TWD)**: `NT$ {total_twd_cost:.3f} TWD` (匯率: {EXCHANGE_RATE_TWD})\n"
            f"- *註記：此費用係以 2026/07/07 官方公開標價計算，僅供參考*\n\n"
        )
        if isinstance(report_target, list):
            report_target.append("\n" + "---" + "\n")
            report_target.append(report_text)
        elif hasattr(report_target, "write"):
            report_target.write(report_text)
            report_target.flush()


def parse_arguments():
    """解析命令列參數"""
    parser = argparse.ArgumentParser(
        description='[GEMINI-AGENT] Playwright 自動化代理 - AI 瀏覽器控制系統',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
[USAGE] 使用範例：
  基本用法：
    python agent.py "搜尋 Python 教學"
    python agent.py "前往 GitHub 並登入"
  
  指定模型：
    python agent.py -m gemini-2.0-flash-exp "搜尋資料"
  
  指定初始網址：
    python agent.py --url https://www.bing.com "搜尋資料"
    python agent.py --url http://localhost:8000 "測試本地網站"
  
  指定要模擬的裝置類型：
    桌上型瀏覽器 (Desktop)： python agent.py -d desktop "測試網站"
    手機版 (Mobile)：        python agent.py -d mobile "測試網站"
    平板版 (Tablet)：        python agent.py -d tablet "測試網站"
  
  組合參數：
    python agent.py -m gemini-2.0-flash-exp -r tester -b verbose "完整測試"
    python agent.py --url https://example.com -r scraper "收集資料"
    python agent.py --record "執行測試並將記錄保存到 records/ 目錄中"
  
  查看配置：
    python agent.py --show-config
    python agent.py --help

[NOTE] 所有參數都會覆蓋 config.py 中的預設值
        """
    )
    
    parser.add_argument('content', nargs='*', 
                       help='要執行的任務（例如：「搜尋 Python」、「前往 Google」）')
    
    parser.add_argument('-t', '--task', type=str, 
                       help=f'明確指定任務內容，覆蓋位置參數。預設：{DEFAULT_TASK[:40]}...')
    
    parser.add_argument('-m', '--model', type=str, default=MODEL_NAME, 
                       help=f'指定 Gemini 模型。可用：gemini-2.0-flash-exp, gemini-3.5-flash 等。預設：{MODEL_NAME}')
    
    parser.add_argument('-r', '--role', type=str, 
                       choices=['default', 'tester', 'scraper', 'shopper', 'researcher'],
                       default=AI_ROLE,
                       help=argparse.SUPPRESS)
    
    parser.add_argument('-b', '--behavior', type=str,
                       choices=['careful', 'fast', 'verbose', 'silent'],
                       default=AI_BEHAVIOR,
                       help=argparse.SUPPRESS)

    parser.add_argument('-o', '--output', type=str,
                       choices=['natural', 'json', 'list', 'table'],
                       default=OUTPUT_FORMAT,
                       help=argparse.SUPPRESS)
    
    parser.add_argument('--max-turns', type=int, default=MAX_TURNS,
                       help=f'AI 最大執行回合數（避免無限循環）。預設：{MAX_TURNS}')
    
    parser.add_argument('--url', type=str, default=INITIAL_URL,
                       help=f'啟動時的初始網址。預設：{INITIAL_URL}')
    
    parser.add_argument('--headless', action='store_true', default=HEADLESS,
                       help='在背景執行（不顯示瀏覽器視窗）。適合自動化任務')
    
    parser.add_argument('-d', '--device', type=str,
                       choices=['desktop', 'mobile', 'tablet'],
                       default='desktop',
                       help='指定要模擬的裝置類型。desktop=傳統桌上型瀏覽器, mobile=模擬 iPhone 13 (觸控與 RWD 版面), tablet=模擬 iPad Pro 11 (觸控與 RWD 版面)。預設：desktop')
    
    parser.add_argument('--show-config', action='store_true',
                       help='顯示當前所有配置並退出（不執行任務）')
    
    parser.add_argument('--wcag', type=str, default=None,
                       help='指定要載入的 WCAG 2.2 章節規則（例如：1.1, 1.3, 2.1）。指定後系統會自動將該章節的無障礙規則加入任務提示詞中，節省 Token 並提高專注度。')
    
    parser.add_argument('--record', action='store_true', default=False,
                       help='啟用執行過程的記錄（儲存截圖、Markdown 報告與運行日誌至 records 目錄）。預設不儲存。')
    
    parser.add_argument('--sitemap', type=str, default=None,
                       help='指定網站地圖路徑（JSON 格式網址清單）。指定後靜態巡檢將直接對地圖內的網址進行掃描。')
    
    parser.add_argument('--generate-sitemap', action='store_true', default=False,
                       help='啟動 AI 進行網站結構探索，並將發現的所有同源子頁面網址繪製成網站地圖 sitemap.json。')
    
    return parser.parse_args()


def get_interaction_tokens(interaction) -> dict:
    """
    從互動物件提取 token 使用量資訊
    傳回格式: {"input": int, "output": int, "total": int}
    """
    tokens = {"input": 0, "output": 0, "total": 0}
    if not interaction:
        return tokens
        
    # 1. 檢查是否為 Claude 互動物件
    if hasattr(interaction, "usage") and isinstance(interaction.usage, dict):
        tokens["input"] = interaction.usage.get("input_tokens", 0)
        tokens["output"] = interaction.usage.get("output_tokens", 0)
        tokens["total"] = interaction.usage.get("total_tokens", 0)
        return tokens
        
    # 2. 檢查是否為 Gemini 互動物件
    usage = getattr(interaction, "usage", None)
    if usage:
        tokens["input"] = getattr(usage, "total_input_tokens", 0) or getattr(usage, "input_token_count", 0) or 0
        tokens["output"] = getattr(usage, "total_output_tokens", 0) or getattr(usage, "output_token_count", 0) or 0
        tokens["total"] = getattr(usage, "total_tokens", 0) or getattr(usage, "total_token_count", 0) or 0
        
    return tokens


def is_wcag_guideline_static(wcag_ver: str) -> bool:
    """
    判斷特定的 WCAG 指南是否主要是靜態代碼審查（可以完全由 Axe-core / 本地腳本覆蓋）
    """
    static_guidelines = ["1.1", "1.2", "1.3", "1.4", "3.1", "3.2", "3.3", "4.1"]
    for sg in static_guidelines:
        if wcag_ver.startswith(sg):
            return True
    return False


def perform_ai_login_phase(page, model_name, username, password):
    """
    執行 AI 預先登入階段。使用有限回合的 AI 交互，
    引導 AI 自動在目前頁面上填寫帳號密碼並完成登入。
    """
    print(f"\n[AI LOGIN] 啟動 AI 預先登入程序...")
    print(f"  - 使用模型: {model_name}")
    print(f"  - 帳號: {username}")
    
    is_claude = model_name.lower().startswith("claude-")
    if is_claude:
        from claude_client import ClaudeAgent
        agent = ClaudeAgent(role="default", behavior="careful", output_format="natural", model=model_name)
    else:
        from gemini_client import GeminiAgent
        agent = GeminiAgent(role="default", behavior="careful", output_format="natural", model=model_name)
        
    login_prompt = (
        f"請使用帳號 '{username}' 與密碼 '{password}' 登入此網站。\n"
        "1. 首先判斷當前畫面是否為登入頁面。如果已經在登入狀態（或非登入頁面），請立刻使用文字說明並結束任務。\n"
        "2. 如果是登入頁面，為了避免現代前端框架（如 React/Vue）的狀態綁定（state binding）失效，請『務必使用滑鼠點擊輸入框』並『使用鍵盤打字 (type/key)』來填寫帳號與密碼，『絕對不要』使用 Javascript (evaluate_javascript) 直接修改欄位的 value。\n"
        "3. 點擊登入按鈕，並等待登入跳轉完成。\n"
        "4. 登入成功進入後台儀表板或首頁後，請立刻結束任務（不要進行任何無障礙檢測，直接完成任務）。"
    )
    
    viewport_width = 1024 if is_claude else 1440
    viewport_height = 768 if is_claude else 900
    
    try:
        login_input_tokens = 0
        login_output_tokens = 0
        login_total_tokens = 0
        
        screenshot_bytes = page.screenshot(type="png")
        from browser_actions import scan_focus_path
        focus_map = scan_focus_path(page)
        
        focus_map_text = ""
        if focus_map:
            table_lines = [
                "\n\n### 🔍 本地自動化焦點順序地圖 (Focus Map)",
                "| 順序 | 標籤 (Tag) | 識別碼 (ID) | 文字內容 |",
                "| :--- | :--- | :--- | :--- |"
            ]
            for item in focus_map[:20]:
                table_lines.append(f"| {item['index']} | {item['tagName']} | `{item['id']}` | {item['text']} |")
            focus_map_text = "\n".join(table_lines)
            
        extra_instructions = f"\n\n{focus_map_text}\n\n請以最快、最有效率的步驟完成登入，一旦登入完成看到主頁/後台，請不要做任何其他操作，直接停止呼叫工具以結束任務。"
        
        interaction = agent.create_initial_interaction(login_prompt, screenshot_bytes, extra_instructions)
        
        # 紀錄初始互動 Token 消耗
        init_tokens = get_interaction_tokens(interaction)
        login_input_tokens += init_tokens["input"]
        login_output_tokens += init_tokens["output"]
        login_total_tokens += init_tokens["total"]
        
        max_login_turns = MAX_LOGIN_TURNS
        for turn in range(max_login_turns):
            print(f"[AI LOGIN] [回合 {turn + 1}/{max_login_turns}]")
            
            text_response = agent.extract_text_response(interaction)
            if text_response.strip():
                print(f"[AI LOGIN] AI: {text_response}")
                
            if not agent.has_function_calls(interaction):
                print("[AI LOGIN] [✓] AI 結束登入操作。")
                break
                
            results = execute_function_calls(interaction, page, viewport_width, viewport_height)
            function_responses = get_function_responses(page, results, interaction)
            
            interaction = agent.continue_interaction(interaction.id, function_responses)
            
            # 紀錄該回合 Token 消耗
            turn_tokens = get_interaction_tokens(interaction)
            login_input_tokens += turn_tokens["input"]
            login_output_tokens += turn_tokens["output"]
            login_total_tokens += turn_tokens["total"]
            
        # 二次驗證：等待並確認是否成功跳轉/登入（密碼輸入框是否消失）
        print("[AI LOGIN] 正在等待登入跳轉並驗證狀態...")
        try:
            # 給予額外的 2 秒等待以完成重導向載入
            page.wait_for_timeout(2000)
            page.wait_for_load_state("load", timeout=3000)
        except Exception:
            pass

        # 檢測密碼欄位是否仍然存在且可見，如果存在代表可能登入失敗
        is_still_login_page = False
        try:
            pw_field = page.query_selector("input[type='password']")
            if pw_field and pw_field.is_visible():
                is_still_login_page = True
        except Exception:
            pass

        if is_still_login_page:
            print("[AI LOGIN] [WARNING] 警告：密碼輸入欄位依然存在，可能認證失敗或尚未成功送出！")
        else:
            print("[AI LOGIN] [✓] 登入驗證成功！密碼欄位已消失，瀏覽器已成功切換至登入後頁面。")
            
        print("[AI LOGIN] [✓] 預登入程序結束，回傳控制權給靜態掃描器。\n")
        return {
            "input": login_input_tokens,
            "output": login_output_tokens,
            "total": login_total_tokens
        }
    except Exception as e:
        print(f"[AI LOGIN] [WARNING] AI 預登入出錯: {e}")
        return {
            "input": 0,
            "output": 0,
            "total": 0
        }


def handle_auto_login(page, username, password):
    """
    自動嘗試在登入頁面輸入帳號密碼並登入
    """
    print("[*] 偵測到已提供登入資訊，嘗試自動登入...")
    try:
        # 1. 尋找密碼欄位
        password_input = page.query_selector("input[type='password']")
        if not password_input:
            print("[WARNING] 未找到密碼欄位，跳過自動登入。")
            return False
            
        # 2. 尋找帳號欄位 (有些網頁只需要密碼)
        username_input = page.query_selector("input[type='text']:not([style*='display: none']):not([style*='visibility: hidden'])")
        if not username_input:
            username_input = page.query_selector("#username, #login-username, input[name='username'], input[name='user']")
            
        if username_input and username:
            print(f"[*] 輸入帳號: {username}")
            username_input.fill(username)
            
        print("[*] 輸入密碼...")
        password_input.fill(password)
        
        # 3. 尋找並點擊登入按鈕
        login_btn = page.query_selector("button[type='submit'], input[type='submit'], #login-btn, #login_btn, button:has-text('Login'), button:has-text('登入')")
        if not login_btn:
            login_btn = page.query_selector("button, input[type='button']")
            
        if login_btn:
            print("[*] 點擊登入按鈕...")
            login_btn.click()
        else:
            print("[*] 未找到登入按鈕，嘗試在密碼欄位發送 Enter 鍵...")
            password_input.press("Enter")
            
        page.wait_for_timeout(3000)
        print("[✓] 自動登入步驟完成。")
        return True
    except Exception as e:
        print(f"[WARNING] 自動登入失敗: {e}")
        return False


def perform_local_site_audit(page, base_url: str, wcag_ver: str, sitemap_path: str = None) -> dict:
    """
    在本地執行同源網站的自動化網頁爬取與 Axe-core/自訂無障礙檢測
    """
    print(f"[*] 啟動本地全站自動化無障礙檢測，目標指南: WCAG {wcag_ver}...")
    
    # 1. 取得網站所有同源連結
    loaded_from_sitemap = False
    urls = []
    if sitemap_path and os.path.exists(sitemap_path):
        try:
            with open(sitemap_path, "r", encoding="utf-8") as sf:
                raw_data = json.load(sf)
                if isinstance(raw_data, list) and len(raw_data) > 0:
                    parsed_urls = []
                    for item in raw_data:
                        if isinstance(item, str):
                            parsed_urls.append(item.strip())
                        elif isinstance(item, dict) and "url" in item:
                            parsed_urls.append(item["url"].strip())
                    
                    if parsed_urls:
                        urls = parsed_urls
                        print(f"[*] [SITEMAP] 成功從地圖檔 '{sitemap_path}' 載入 {len(urls)} 個頁面進行檢測。")
                        loaded_from_sitemap = True
                    else:
                        print(f"[WARNING] 地圖檔 '{sitemap_path}' 中未找到任何有效的 URL 欄位，退回自動爬網。")
                else:
                    print(f"[WARNING] 地圖檔 '{sitemap_path}' 格式不正確或為空，退回自動爬網。")
        except Exception as sf_err:
            print(f"[WARNING] 讀取地圖檔 '{sitemap_path}' 失敗: {sf_err}，退回自動爬網。")
            
    if not loaded_from_sitemap:
        get_links_script = """
        (() => {
            const urls = [...new Set(Array.from(document.querySelectorAll('a[href]')).map(a => a.href).filter(href => {
                try {
                    const url = new URL(href);
                    return url.host === window.location.host;
                } catch(e) {
                    return false;
                }
            }))];
            if (!urls.includes(location.href)) urls.push(location.href);
            return urls;
        })()
        """
        try:
            urls = page.evaluate(get_links_script)
        except Exception as e:
            print(f"[WARNING] 無法取得頁面連結: {e}")
            urls = [base_url]

    # 限制最大爬取頁數，自 config 載入以利自訂
    urls = list(set(urls))[:MAX_CRAWL_PAGES]
    print(f"[*] 已規劃巡檢以下 {len(urls)} 個內部頁面: {urls}")
    
    audit_results = {}
    total_violations = 0
    
    clean_ver = wcag_ver.replace(".", "")
    target_tag_prefix = f"wcag{clean_ver}"
    
    for u in urls:
        print(f"[*] 正在本地檢測頁面: {u}")
        try:
            # 導航至該頁面 (採用漸進式導航，優先使用客戶端跳轉以防止 SPA 內存中的 Session 被重置)
            nav_success = False
            try:
                from urllib.parse import urlparse
                parsed_url = urlparse(u)
                path = parsed_url.path
                
                # 1. 尋找對應 href 的 <a> 連結並點擊，以觸發真實的 React/Vue 路由跳轉
                if path and path != "/" and "login" not in path.lower():
                    link = page.query_selector(f"a[href$='{path}'], a[href='{path}']")
                    if link and link.is_visible():
                        link.click()
                        page.wait_for_timeout(1000)
                        # 如果當前網址不包含 /login，表示成功跳轉
                        if "login" not in page.url.lower():
                            nav_success = True
                            
                # 2. 若點擊不可行，嘗試使用 HTML5 History API 進行無刷新客戶端跳轉
                if not nav_success:
                    page.evaluate(f"window.history.pushState(null, '', '{u}'); window.dispatchEvent(new PopStateEvent('popstate'));")
                    page.wait_for_timeout(800)
                    if "login" not in page.url.lower():
                        nav_success = True
            except Exception as nav_err:
                print(f"[INFO] 客戶端無刷新導航嘗試失敗: {nav_err}，改用傳統載入。")
                
            # 3. 最終降級：使用傳統的 page.goto 重載頁面
            if not nav_success:
                try:
                    page.goto(u, wait_until="domcontentloaded")
                    page.wait_for_timeout(1000)
                except Exception as goto_err:
                    print(f"[WARNING] 導航至 {u} 失敗: {goto_err}")
            
            # 取得頁面診斷資訊，驗證是否為空網頁或未渲染完成
            title = "N/A"
            html_len = 0
            elements_count = 0
            try:
                title = page.title()
                html_len = len(page.content())
                elements_count = page.evaluate("document.getElementsByTagName('*').length")
            except Exception as diag_err:
                print(f"[WARNING] 無法獲取頁面診斷資訊: {diag_err}")
                
            print(f"    - 頁面標題: '{title}'")
            print(f"    - HTML 大小: {html_len} bytes, DOM 元素數: {elements_count}")
            
            # 執行 Axe-core 審查
            axe_res = run_axe_audit(page)
            violations = axe_res.get("violations", [])
            
            # 過濾對應的 WCAG 條款
            matched_violations = []
            for vio in violations:
                is_match = False
                for tag in vio.get("tags", []):
                    if tag.startswith(target_tag_prefix):
                        is_match = True
                        break
                if is_match:
                    matched_violations.append(vio)
            
            # 如果是 WCAG 1.2，再額外做媒體元素檢測
            media_info = None
            if wcag_ver.startswith("1.2"):
                media_check_script = """
                (() => {
                    const audio = document.querySelectorAll('audio').length;
                    const video = document.querySelectorAll('video').length;
                    const iframe = document.querySelectorAll('iframe').length;
                    const embed = document.querySelectorAll('embed').length;
                    const object = document.querySelectorAll('object').length;
                    return audio + video + iframe + embed + object;
                })()
                """
                media_count = page.evaluate(media_check_script)
                media_info = {"media_count": media_count}
                
            audit_results[u] = {
                "title": title,
                "elements": elements_count,
                "violations": matched_violations,
                "media_info": media_info,
                "status": "PASS" if not matched_violations else "FAIL"
            }
            total_violations += len(matched_violations)
            
        except Exception as e:
            print(f"[WARNING] 檢測頁面 {u} 失敗: {e}")
            audit_results[u] = {
                "violations": [],
                "error": str(e),
                "status": "ERROR"
            }
            
    return {
        "results": audit_results,
        "total_violations": total_violations
    }


def check_task_suitability_for_axe(task: str, extra_instructions: str, model: str) -> tuple:
    """
    透過輕量級 AI 呼叫，評估當前任務是否只需使用 Axe-core 代碼審查工具即可解決。
    """
    print("[*] Evaluating if task can be resolved using local Axe-core tool (code audit)...")
    prompt = (
        "你是一個 Web 無障礙檢測架構分析專家。請分析以下使用者要求及注入的 WCAG 2.2 規範。\n"
        "判斷該任務「是否只需要檢查 HTML 代碼結構、屬性（如是否有 alt、ID是否唯一、ARIA是否正確）」，也就是說「完全不需要進行任何滑鼠點擊、鍵盤輸入、視覺對比度確認或動態互動，只需使用代碼檢測工具（如 Axe-core）即可完全解決」。\n\n"
        f"【使用者任務描述】:\n{task}\n\n"
        f"【載入的無障礙規則】:\n{extra_instructions}\n\n"
        "請以下列格式回覆（請僅回覆這兩行，不要有其他字元）：\n"
        "DECISION: [YES 或 NO]\n"
        "REASON: [簡短的分析說明原因]\n"
    )
    
    is_claude = model.lower().startswith("claude-")
    try:
        if is_claude:
            from claude_client import ClaudeAgent
            agent = ClaudeAgent(model=model)
            # 確保使用一般文字模型，不強制使用 computer 預覽版工具限制
            target_model = agent.model
            if "computer-use" in target_model:
                target_model = "claude-3-5-sonnet-20241022"
            response = agent.client.messages.create(
                model=target_model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )
            reply = response.content[0].text
        else:
            from gemini_client import GeminiAgent
            agent = GeminiAgent(model=model)
            # 強制使用輕量級文字模型 gemini-2.5-flash，避免 computer-use 專用模型報錯
            response = agent.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            reply = response.text
            
        decision = "NO"
        reason = "無法判定，預設使用視覺 AI 代理。"
        for line in reply.split("\n"):
            if line.startswith("DECISION:"):
                decision = line.replace("DECISION:", "").strip().upper()
            elif line.startswith("REASON:"):
                reason = line.replace("REASON:", "").strip()
                
        is_axe_only = (decision == "YES")
        return is_axe_only, reason
    except Exception as e:
        print(f"[WARNING] AI suitability evaluation failed: {e}. Defaulting to Visual AI.")
        return False, "Evaluation failed due to API error."


def main():
    args = parse_arguments()
    
    # 顯示配置
    if args.show_config:
        print("\n" + "="*60)
        print("[CONFIG] Current Configuration")
        print("="*60)
        print(f"  model              : {args.model}")
        print(f"  tool_type          : {TOOL_TYPE}")
        print(f"  tool_environment   : {TOOL_ENVIRONMENT}")
        print(f"  role               : {args.role}")
        print(f"  behavior           : {args.behavior}")
        print(f"  output_format      : {args.output}")
        print(f"  device_mode        : {args.device}")
        print(f"  headless_mode      : {args.headless}")
        print(f"  initial_url        : {args.url}")
        print(f"  default_task       : {DEFAULT_TASK}")
        print(f"  observation_time   : {RESULT_OBSERVATION_TIME}s")
        print(f"  prompt_injection   : {ENABLE_PROMPT_INJECTION_DETECTION}")
        print("="*60 + "\n")
        return
    
    # 決定任務
    if args.generate_sitemap:
        user_task = "請登入網站，並點擊展開每一個選單、每一個設定分頁以探索全站所有能存取的主功能與子頁面路徑。一旦發現任何新的同源 URL 路由，請記錄下來。任務結束時，請在您的最後回覆中，以標準的 JSON 陣列格式輸出您發現的所有獨特網址路徑清單，例如：[\"http://localhost:8000/\", \"http://localhost:8000/advanced\", \"http://localhost:8000/advanced/network/wifi/settings\"]。請確保只返回該 JSON 網址陣列且格式正確，這對後續的測試十分重要。"
    elif args.task:
        user_task = args.task
    elif args.content:
        user_task = " ".join(args.content)
    else:
        user_task = DEFAULT_TASK
        
    extra_instructions = ""
    global_total_input_tokens = 0
    global_total_output_tokens = 0
    printed_token_summary = False
    if args.wcag:
        filename = f"guideline_{args.wcag.replace('.', '_')}.md"
        filepath = os.path.join("documentation", "wcag_rules", filename)
        if os.path.exists(filepath):
            print(f"[*] Loading WCAG 2.2 rules from: {filepath}")
            with open(filepath, "r", encoding="utf-8") as f:
                rules_content = f.read()
            extra_instructions = f"\n\n請務必依據以下 WCAG 2.2 規範進行驗證及操作：\n\n{rules_content}\n\n" \
                                 f"**【⚠️ 核心無障礙審查操作指引 - 避免無意義消耗】**\n" \
                                 f"1. **審查範圍與限制**：審查的預設範圍為「整個網站」（當前 Host 下的所有內部頁面）。如果頁面中包含連結至其他獨立網站的「外部連結」（即 Host 不同的網址），請**絕對不要點擊或進行處理**，外部連結不在審查範圍內。\n" \
                                 f"2. **快速判定不適用 (N/A) 原則**：請先使用專屬工具 `evaluate_javascript` 查詢當前頁面或點擊導航至其他內部子頁面。如果在整個網站的所有內部頁面上，完全沒有任何與該 WCAG 指南相關的 HTML 元素或組件（例如對於 Guideline 1.2 時基媒體，若整個網站根本沒有任何 `<audio>`、`<video>` 元素、`<iframe>` 嵌入影片或多媒體播放器），請在巡檢完內部頁面後結束任務，回報「該網站不包含任何相關媒體元素，此指南不適用（PASS / N/A）」。請有條理地進行內部子頁面導航，避免重覆訪問相同頁面。\n" \
                                 f"3. **禁止無效的系統嘗試**：請勿試圖按 F12、Ctrl+Shift+I 或以滑鼠右鍵開啟瀏覽器開發者工具（DevTools），也不要嘗試在地址欄輸入 `javascript:` 偽協定或使用 `data:` URL，這些在沙盒瀏覽器中均被安全機制封鎖或無法顯示。請直接使用專屬工具 `evaluate_javascript` 來讀取 DOM、或使用 `run_axe_audit` 進行無障礙代碼檢測。\n" \
                                 f"4. **【💡 全站高效率掃描技巧】**：若要快速檢查整個網站的所有頁面是否包含特定標籤（如 `<audio>`、`<video>`、`<iframe>` 等），您不需要逐頁點擊與等待，可在首頁直接執行非同步 fetch 掃描所有內部連結的 HTML（例如：`(async () => {{ const urls = [...new Set(Array.from(document.querySelectorAll('a[href]')).map(a => a.href).filter(href => href.startsWith(location.origin)))]; const res = {{}}; for (const u of urls) {{ try {{ const text = await (await fetch(u)).text(); res[u] = /<video|<audio|<iframe|<embed|<object/i.test(text); }} catch(e) {{ res[u] = 'error'; }} }} return res; }})()`）。這可以讓您在 1 回合內檢測完所有子頁面，省去手動逐頁 Navigate 與等待的時間！"
        else:
            print(f"[WARNING] WCAG rules file {filepath} not found. Running without injected rules.")
            
    # 進行適用度評估：若有 WCAG 指南，優先套用 rule-based 靜態與動態判定，免去 AI 評估成本
    is_axe_only = False
    axe_reason = ""
    if args.generate_sitemap:
        is_axe_only = False
        axe_reason = "啟動 AI 全站地圖探索繪製任務。"
    elif args.wcag:
        if is_wcag_guideline_static(args.wcag):
            is_axe_only = True
            axe_reason = f"WCAG {args.wcag} 為靜態可檢測指南，已套用本地自動化全站巡檢引擎。"
        else:
            is_axe_only = False
            axe_reason = f"WCAG {args.wcag} 為動態互動指南，需要視覺與鍵盤互動，啟動 AI 巡檢。"
    else:
        # 非 WCAG 指南任務，再由輕量級 AI 判定是否為 Axe 靜態任務
        is_axe_only, axe_reason = check_task_suitability_for_axe(user_task, extra_instructions, args.model)

    if is_axe_only:
        print("\n" + "="*60)
        print("🎯 任務評估：此任務可透過本地代碼與結構巡檢解決！")
        print(f"  原因說明：{axe_reason}")
        print("="*60)
        print("[*] 啟動本地自動化無障礙檢測引擎...")
        
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=args.headless)
        context = browser.new_context(
            viewport={"width": 1024, "height": 768}
        )
        page = context.new_page()
        page.add_init_script("window.addEventListener('contextmenu', e => e.preventDefault(), true);")
        
        target_url = args.url or INITIAL_URL
        print(f"[>>] 正在導航至目標頁面: {target_url}")
        try:
            page.goto(target_url, wait_until="domcontentloaded")
            
            # 若配置了自動登入資訊，則在爬取前執行 AI 預先登入
            from config import AUTO_LOGIN_USERNAME, AUTO_LOGIN_PASSWORD
            if AUTO_LOGIN_USERNAME or AUTO_LOGIN_PASSWORD:
                login_toks = perform_ai_login_phase(page, args.model, AUTO_LOGIN_USERNAME, AUTO_LOGIN_PASSWORD)
                global_total_input_tokens += login_toks["input"]
                global_total_output_tokens += login_toks["output"]
            
            # 建立報告內容與檔名
            report_lines = []
            raw_results = {}
            
            if args.wcag:
                # 執行本地全站自動巡檢
                audit_res = perform_local_site_audit(page, target_url, args.wcag, sitemap_path=args.sitemap)
                total_violations = audit_res["total_violations"]
                
                print(f"[✓] 本地全站巡檢完成！共發現 {total_violations} 個無障礙違規項目。")
                print("="*60)
                
                report_lines.append(f"# 📝 WCAG {args.wcag} 本地自動化無障礙全站巡檢報告\n")
                report_lines.append(f"- **檢測目標主頁**: {target_url}")
                report_lines.append(f"- **檢測時間**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                report_lines.append(f"- **巡檢子頁面總數**: {len(audit_res['results'])}")
                report_lines.append(f"- **發現違規項目總數**: {total_violations}\n")
                
                # 統計各頁面狀態
                report_lines.append("## 📊 巡檢頁面狀態一覽")
                report_lines.append("| 子頁面網址 | 頁面標題 | DOM 元素數 | 狀態 | 違規數量 |")
                report_lines.append("| :--- | :--- | :---: | :---: | :---: |")
                for page_url, info in audit_res["results"].items():
                    status_emoji = "✅ PASS" if info["status"] == "PASS" else "❌ FAIL"
                    if info.get("error"):
                        status_emoji = "⚠️ ERROR"
                    title = info.get("title", "N/A")
                    elements = info.get("elements", "N/A")
                    report_lines.append(f"| {page_url} | {title} | {elements} | {status_emoji} | {len(info.get('violations', []))} |")
                report_lines.append("\n" + "---" + "\n")
                
                # 詳細違規詳情
                report_lines.append("## ❌ 違規詳情列表\n")
                for page_url, info in audit_res["results"].items():
                    if info.get("violations"):
                        report_lines.append(f"### 🌐 頁面: {page_url}\n")
                        for idx, vio in enumerate(info["violations"]):
                            vio_id = vio.get("id", "N/A")
                            impact = vio.get("impact", "N/A").upper()
                            desc = vio.get("description", "")
                            help_msg = vio.get("help", "")
                            help_url = vio.get("helpUrl", "")
                            nodes = vio.get("nodes", [])
                            
                            report_lines.append(f"#### {idx+1}. [{impact}] {vio_id} - {help_msg}")
                            report_lines.append(f"- **描述**: {desc}")
                            report_lines.append(f"- **規範說明連結**: [{vio_id} 說明]({help_url})")
                            report_lines.append(f"- **受影響元素數量**: {len(nodes)}")
                            report_lines.append("\n**受影響的 HTML 節點與 CSS 選擇器**:")
                            
                            for node_idx, node in enumerate(nodes[:5]):
                                selector = ", ".join(node.get("target", []))
                                html_snippet = node.get("html", "")
                                summary = node.get("failureSummary", "")
                                
                                report_lines.append(f"  - 節點 {node_idx+1}: `{selector}`")
                                report_lines.append(f"    - HTML: `{html_snippet}`")
                                report_lines.append(f"    - 修復建議: {summary}")
                            
                            if len(nodes) > 5:
                                report_lines.append(f"  - *(其餘 {len(nodes) - 5} 個節點已省略)*")
                            report_lines.append("")
                
                raw_results = audit_res
            else:
                # 傳統單頁 Axe-core 審查
                print("[+] 正在提取網頁 DOM 結構進行無障礙審查...")
                
                title = "N/A"
                html_len = 0
                elements_count = 0
                try:
                    title = page.title()
                    html_len = len(page.content())
                    elements_count = page.evaluate("document.getElementsByTagName('*').length")
                except Exception as diag_err:
                    pass
                print(f"    - 頁面標題: '{title}'")
                print(f"    - HTML 大小: {html_len} bytes, DOM 元素數: {elements_count}")
                
                axe_results = run_axe_audit(page)
                violations = axe_results.get("violations", [])
                
                print(f"[✓] 本地代碼檢測完成！共發現 {len(violations)} 個無障礙違規項目。")
                print("="*60)
                
                report_lines.append("# 📝 Axe-core 無障礙靜態審查報告\n")
                report_lines.append(f"- **檢測目標網址**: {target_url}")
                report_lines.append(f"- **頁面標題**: {title}")
                report_lines.append(f"- **DOM 元素數**: {elements_count}")
                report_lines.append(f"- **檢測時間**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                report_lines.append(f"- **違規項目總數**: {len(violations)}\n")
                report_lines.append("## ❌ 違規詳情列表\n")
                
                if not violations:
                    report_lines.append("🎉 恭喜！未發現任何靜態無障礙違規項目。")
                    print("🎉 恭喜！未發現任何靜態無障礙違規項目。")
                else:
                    for idx, vio in enumerate(violations):
                        vio_id = vio.get("id", "N/A")
                        impact = vio.get("impact", "N/A").upper()
                        desc = vio.get("description", "")
                        help_msg = vio.get("help", "")
                        help_url = vio.get("helpUrl", "")
                        nodes = vio.get("nodes", [])
                        
                        report_lines.append(f"### {idx+1}. [{impact}] {vio_id} - {help_msg}")
                        report_lines.append(f"- **描述**: {desc}")
                        report_lines.append(f"- **規範說明連結**: [{vio_id} 說明]({help_url})")
                        report_lines.append(f"- **受影響元素數量**: {len(nodes)}")
                        report_lines.append("\n**受影響的 HTML 節點與 CSS 選擇器**:")
                        
                        print(f"\n❌ [{impact}] {vio_id}: {help_msg}")
                        print(f"   描述: {desc}")
                        print(f"   影響元素數: {len(nodes)}")
                        
                        for node_idx, node in enumerate(nodes[:5]):
                            selector = ", ".join(node.get("target", []))
                            html_snippet = node.get("html", "")
                            summary = node.get("failureSummary", "")
                            
                            report_lines.append(f"  - 節點 {node_idx+1}: `{selector}`")
                            report_lines.append(f"    - HTML: `{html_snippet}`")
                            report_lines.append(f"    - 修復建議: {summary}")
                            
                            if node_idx == 0:
                                print(f"   - 範例節點: {selector}")
                                print(f"     範例 HTML: {html_snippet}")
                                print(f"     修復建議: {summary}")
                                
                        if len(nodes) > 5:
                            report_lines.append(f"  - *(其餘 {len(nodes) - 5} 個節點已省略)*")
                        report_lines.append("")
                raw_results = axe_results

            # 獲取頁面截圖作為首頁示意圖供 AI 參考
            screenshot_bytes = b""
            try:
                screenshot_bytes = page.screenshot(type="png")
            except Exception as e:
                print(f"[WARNING] 擷取頁面截圖失敗: {e}")

            # 進行 AI 智慧診斷與評估
            is_claude = args.model.lower().startswith("claude-")
            has_key = CLAUDE_API_KEY if is_claude else GEMINI_API_KEY
            
            if has_key:
                print("\n[AI] 正在將本地檢測結果遞交給 AI 進行智慧診斷與評估...")
                try:
                    # 整理傳遞給 AI 的檢測結果摘要
                    summary_for_ai = []
                    if "results" in raw_results:  # 全站巡檢
                        for page_url, page_info in raw_results["results"].items():
                            summary_for_ai.append(f"子網頁: {page_url}")
                            violations = page_info.get("violations", [])
                            if not violations:
                                summary_for_ai.append("  - 狀態: 無任何違規項目 (PASS)")
                            else:
                                summary_for_ai.append(f"  - 發現 {len(violations)} 個違規項目:")
                                for vio in violations:
                                    summary_for_ai.append(f"    * 違規項目ID: {vio.get('id')} ({vio.get('help')}) - 嚴重程度: {vio.get('impact')}")
                                    summary_for_ai.append(f"      描述: {vio.get('description')}")
                                    summary_for_ai.append("      受影響節點樣例:")
                                    for node in vio.get("nodes", [])[:3]:
                                        summary_for_ai.append(f"        - 選擇器: {', '.join(node.get('target', []))}")
                                        summary_for_ai.append(f"          HTML: {node.get('html')}")
                                        summary_for_ai.append(f"          修復建議: {node.get('failureSummary')}")
                    else:  # 單頁巡檢
                        violations = raw_results.get("violations", [])
                        if not violations:
                            summary_for_ai.append("狀態: 無任何違規項目 (PASS)")
                        else:
                            summary_for_ai.append(f"發現 {len(violations)} 個違規項目:")
                            for vio in violations:
                                summary_for_ai.append(f"  * 違規項目ID: {vio.get('id')} ({vio.get('help')}) - 嚴重程度: {vio.get('impact')}")
                                summary_for_ai.append(f"    描述: {vio.get('description')}")
                                summary_for_ai.append("    受影響節點樣例:")
                                for node in vio.get("nodes", [])[:3]:
                                    summary_for_ai.append(f"      - 選擇器: {', '.join(node.get('target', []))}")
                                    summary_for_ai.append(f"        HTML: {node.get('html')}")
                                    summary_for_ai.append(f"        修復建議: {node.get('failureSummary')}")
                    
                    ai_data_text = "\n".join(summary_for_ai)
                    
                    # 初始化 AI 代理
                    if is_claude:
                        ai_agent = ClaudeAgent(role=args.role, behavior=args.behavior, output_format=args.output, model=args.model)
                    else:
                        ai_agent = GeminiAgent(role=args.role, behavior=args.behavior, output_format=args.output, model=args.model)
                    
                    ai_response = ai_agent.diagnose_static_audit(target_url, ai_data_text, screenshot_bytes, wcag_guideline=args.wcag)
                    ai_text = ai_response["text"]
                    ai_usage = ai_response["usage"]
                    global_total_input_tokens += ai_usage["input"]
                    global_total_output_tokens += ai_usage["output"]
                    
                    print("\n" + "="*60)
                    print("🤖 AI 智慧診斷與評估報告")
                    print("="*60)
                    print(ai_text)
                    print("="*60 + "\n")
                    
                    report_lines.append("\n" + "---" + "\n")
                    report_lines.append("## 🤖 AI 智慧診斷與評估報告\n")
                    report_lines.append(ai_text)
                    
                    # 輸出 Token 統計與計費資訊至主控台與報告中
                    print_token_and_cost_summary(args.model, global_total_input_tokens, global_total_output_tokens, report_lines)
                    printed_token_summary = True
                    
                except Exception as ai_err:
                    print(f"[WARNING] AI 智慧診斷調用失敗: {ai_err}")
            else:
                print("[INFO] 未偵測到對應的 API Key，跳過 AI 智慧診斷。")

            if args.record:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                record_dir = os.path.join("records", f"axe_run_{timestamp}")
                os.makedirs(record_dir, exist_ok=True)
                
                report_path = os.path.join(record_dir, "report.md")
                with open(report_path, "w", encoding="utf-8") as rf:
                    rf.write("\n".join(report_lines))
                    
                json_path = os.path.join(record_dir, "axe_raw_results.json")
                with open(json_path, "w", encoding="utf-8") as jf:
                    json.dump(raw_results, jf, indent=2, ensure_ascii=False)
                    
                print(f"\n[*] 審查報告已儲存至: {record_dir}")
                
            print("="*60 + "\n")
            
        except Exception as e:
            print(f"[ERROR] 本地代碼巡檢執行失敗: {e}")
        finally:
            browser.close()
            playwright.stop()
        return
    
    is_claude = args.model.lower().startswith("claude-")
    
    # 檢查 API 金鑰
    if is_claude:
        if not CLAUDE_API_KEY:
            print("[ERROR] CLAUDE_API_KEY not found")
            print("[INFO] Set with: $env:CLAUDE_API_KEY = 'your-api-key'")
            print("[INFO] Or create config_local.py with: CLAUDE_API_KEY = 'your-api-key'")
            return
    else:
        if not GEMINI_API_KEY:
            print("[ERROR] GEMINI_API_KEY not found")
            print("[INFO] Set with: $env:GEMINI_API_KEY = 'your-api-key'")
            print("[INFO] Or create config_local.py with: GEMINI_API_KEY = 'your-api-key'")
            return
    
    # 初始化 AI 代理
    if is_claude:
        agent = ClaudeAgent(
            role=args.role,
            behavior=args.behavior,
            output_format=args.output,
            model=args.model
        )
    else:
        agent = GeminiAgent(
            role=args.role,
            behavior=args.behavior,
            output_format=args.output,
            model=args.model
        )
    
    # 啟動瀏覽器
    print("=" * 60)
    print(f"[{'CLAUDE' if is_claude else 'GEMINI'}-AGENT] Playwright Automation System")
    print("=" * 60)
    print(f"\n[TASK]   {user_task}")
    print(f"[MODEL]  {args.model}")
    print(f"[ROLE]   {args.role}")
    print(f"[MODE]   {args.behavior}")
    print(f"[FORMAT] {args.output}\n")
    print("[*] Launching browser...")
    
    playwright = sync_playwright().start()
    
    # 決定裝置模擬與解析度
    device_config = {}
    if args.device == "mobile":
        print("[*] Emulating mobile device: iPhone 13")
        device_config = playwright.devices["iPhone 13"]
        viewport_width = device_config["viewport"]["width"]
        viewport_height = device_config["viewport"]["height"]
    elif args.device == "tablet":
        print("[*] Emulating tablet device: iPad Pro 11")
        device_config = playwright.devices["iPad Pro 11"]
        viewport_width = device_config["viewport"]["width"]
        viewport_height = device_config["viewport"]["height"]
    else:
        # 決定視窗解析度，Claude 預設為 1024x768，Gemini 預設為 SCREEN_WIDTH/SCREEN_HEIGHT
        viewport_width = 1024 if is_claude else SCREEN_WIDTH
        viewport_height = 768 if is_claude else SCREEN_HEIGHT

    browser = playwright.chromium.launch(headless=args.headless)
    
    # 建立 Context：若為行動裝置/平板則載入模擬設定，桌機則套用對應的 viewport
    if args.device in ("mobile", "tablet"):
        context = browser.new_context(**device_config)
    else:
        context = browser.new_context(viewport={"width": viewport_width, "height": viewport_height})
        
    page = context.new_page()
    
    # 阻止瀏覽器預設的右鍵選單彈出（避免在非 headless 模式下反映在本機 OS 上，且網頁截圖無法擷取導致 AI 找不到選單）
    page.add_init_script("window.addEventListener('contextmenu', e => e.preventDefault(), true);")

    # 限制僅能在當前主網域/Host 下進行導航，防止 AI 點擊並跳轉至外部連結
    from urllib.parse import urlparse
    initial_parsed = urlparse(args.url)
    allowed_host = initial_parsed.netloc

    def handle_route(route, request):
        if request.is_navigation_request():
            req_parsed = urlparse(request.url)
            # 如果是導航請求且 Host 不同，則阻止導航（忽略外站連結）
            if req_parsed.netloc and req_parsed.netloc != allowed_host:
                print(f"[*] [BLOCKED] Navigation to external URL aborted: {request.url}")
                route.abort()
                return
        route.continue_()

    page.route("**/*", handle_route)

    # 建立臨時記錄資料夾與報告
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    if args.record:
        record_dir = os.path.join("records", f"run_{timestamp}")
        os.makedirs(record_dir, exist_ok=True)
        print(f"[*] Recording this run to: {record_dir}")
        report_path = os.path.join(record_dir, "report.md")
        log_path = os.path.join(record_dir, "run.log")
        report_file = open(report_path, "w", encoding="utf-8")
        log_file = open(log_path, "w", encoding="utf-8")
    else:
        record_dir = None
        report_file = NullWriter()
        log_file = NullWriter()
        print("[*] Recording is disabled. (Use --record to save execution history)")
    
    report_file.write(f"# AI Playwright Agent 執行報告\n\n")
    report_file.write(f"- **時間戳記**: `{timestamp}`\n")
    report_file.write(f"- **任務內容**: {user_task}\n")
    report_file.write(f"- **AI 模型**: `{args.model}`\n")
    report_file.write(f"- **模擬裝置**: `{args.device}`\n")
    report_file.write(f"- **初始網址**: `{args.url}`\n\n")
    report_file.flush()

    # 初始化 Token 累計變數 (繼承並累計登入階段所產生的 Token 消耗)
    total_input_tokens = global_total_input_tokens
    total_output_tokens = global_total_output_tokens
    total_tokens = total_input_tokens + total_output_tokens

    try:
        # 前往初始頁面
        print(f"[>>] Navigating to: {args.url}")
        page.goto(args.url)
        try:
            page.focus("body")
        except Exception:
            pass

        # 若配置了自動登入資訊，且當前不在 wcag 流程中，在此自訂任務流程中也進行 AI 預先登入
        from config import AUTO_LOGIN_USERNAME, AUTO_LOGIN_PASSWORD
        if AUTO_LOGIN_USERNAME or AUTO_LOGIN_PASSWORD:
            login_toks = perform_ai_login_phase(page, args.model, AUTO_LOGIN_USERNAME, AUTO_LOGIN_PASSWORD)
            global_total_input_tokens += login_toks["input"]
            global_total_output_tokens += login_toks["output"]

        # 進行本地靜態預檢，節省 AI 算力（能省則省原則）
        if args.wcag == "1.2":
            print("[*] 偵測到時基媒體審查任務，啟動本地全站非同步預檢以節省 AI 算力...")
            scan_script = """
            (async () => {
                const urls = [...new Set(Array.from(document.querySelectorAll('a[href]')).map(a => a.href).filter(href => href.startsWith(location.origin)))];
                if (!urls.includes(location.href)) urls.push(location.href);
                const res = {};
                let totalMedia = 0;
                for (const u of urls) {
                    try {
                        const text = await (await fetch(u)).text();
                        const hasMedia = /<video|<audio|<iframe|<embed|<object/i.test(text);
                        res[u] = hasMedia;
                        if (hasMedia) totalMedia++;
                    } catch(e) { res[u] = 'error'; }
                }
                return { results: res, totalMedia: totalMedia };
            })()
            """
            try:
                page.wait_for_timeout(2000)
                precheck_result = page.evaluate(scan_script)
                if precheck_result and precheck_result.get("totalMedia") == 0:
                    print("\n" + "="*60)
                    print("🎯 本地預檢結論：全站所有內部網頁均未發現任何時基媒體元素！")
                    print("   WCAG 2.2 Guideline 1.2（時基媒體）不適用於此網站（PASS / N/A）。")
                    print("   已為您自動通過審查，成功節省 100% AI Token 消耗！")
                    print("="*60 + "\n")
                    
                    if args.record:
                        report_path = os.path.join(record_dir, "report.md")
                        with open(report_path, "w", encoding="utf-8") as rf:
                            rf.write(f"# WCAG 2.2 Guideline 1.2 本地預檢報告\n\n")
                            rf.write(f"- **檢測目標**: {args.url}\n")
                            rf.write(f"- **結果**: ✅ **PASS (Not Applicable)**\n")
                            rf.write(f"- **說明**: 本地自動化腳本掃描了全站 {len(precheck_result['results'])} 個子頁面，確認無任何 `<video>`、`<audio>`、`<iframe>` 等時基媒體元素，無須調用 AI 算力。\n")
                    
                    return
                else:
                    print(f"[*] 本地檢測到 {precheck_result.get('totalMedia')} 個頁面包含潛在媒體元素，啟動 AI 代理進行深度審查...")
            except Exception as e:
                print(f"[WARNING] 本地預檢失敗，將降級啟動 AI 進行全面審查: {e}")
        initial_screenshot = page.screenshot(type="png")
        
        # 儲存初始截圖
        initial_screenshot_name = "step_0_initial.png"
        if record_dir:
            with open(os.path.join(record_dir, initial_screenshot_name), "wb") as f:
                f.write(initial_screenshot)
        report_file.write(f"## 🎬 初始狀態\n")
        report_file.write(f"已導航至 {args.url}，初始畫面如下：\n\n")
        report_file.write(f"![初始截圖]({initial_screenshot_name})\n\n")
        report_file.flush()
        
        # Level 2 Focus Scan (若任務與鍵盤、焦點或 Tab 鍵相關，自動執行焦點掃描並附加於 Prompt)
        is_keyboard_task = any(kw in user_task.lower() or kw in extra_instructions.lower() for kw in ["keyboard", "tab", "focus", "按鍵", "鍵盤", "焦點"])
        if is_keyboard_task:
            print("[*] 偵測到鍵盤或焦點相關任務，啟動本地 Focus-Path 焦點路徑掃描器...")
            
            # 等待前端 React/JS 框架渲染 DOM 完成
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            page.wait_for_timeout(2000)  # 保險等待 2 秒以防動態加載延遲
            
            focus_map = scan_focus_path(page)
            if focus_map:
                print(f"[✓] 掃描完成！共尋找到 {len(focus_map)} 個可聚焦元素。")
                
                table_lines = [
                    "\n\n### 🔍 本地自動化焦點順序地圖 (Focus Map)",
                    "以下為本地 Focus-Path 掃描器自動聚焦遍歷所有元素得到的順序與資訊：\n",
                    "| 順序 | 標籤 (Tag) | 識別碼 (ID) | 類別 (Class) | 文字內容/標題 | 坐標 (X, Y) | 焦點環 CSS 樣式 (Outline) |",
                    "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
                ]
                for item in focus_map:
                    table_lines.append(
                        f"| {item['index']} | {item['tagName']} | `{item['id']}` | `{item['className']}` | {item['text']} | {item['x']},{item['y']} | `{item['outline']}` |"
                    )
                
                focus_map_text = "\n".join(table_lines)
                extra_instructions += f"\n\n{focus_map_text}\n\n**【⚠️ 核心操作指示：請嚴格遵守以節省 Token 且確保無障礙檢測準確性】**\n" \
                                      f"1. **對照視覺與地圖 (關鍵)**：上表為本地能被 focus() 的元素。請仔細觀察螢幕截圖中的所有「視覺上可互動元素」（例如選單、按鈕、以及特別注意分頁標籤如 **IPv4/IPv6**、**2.4GHz/5GHz** 等）。如果截圖中看得見某個互動元素，但它**不在**上表的 Focus Map 中，代表該元素「完全無法被鍵盤聚焦」，這是嚴重的 **WCAG 2.1.1 (Keyboard) 違規**！請直接在結論中指出此違規，並說明哪些元素缺失。\n" \
                                      f"2. **禁止無意義遍歷**：你**絕對不需要**手動按 Tab 鍵逐一走過上表每一個正常的元素！請直接利用 Focus Map 進行靜態對照與分析。\n" \
                                      f"3. **針對疑點標靶測試**：你**只需要針對有疑慮的 1~2 個特定元素**（例如有視覺標籤但地圖中缺失的元素，或是地圖中顯示 `outline: none` 的元素）進行鍵盤按鍵或點擊實體切換，以驗證其是否可以被 Enter (Return) 鍵激活，或確認是否真的無法聚焦。\n" \
                                      f"4. **多鍵發送捷徑**：如果你需要按多次 Tab 鍵來到達某個元素，你可以將按鍵以空格分隔在同一個指令中發送（例如：`\"text\": \"Tab Tab Tab Tab\"`），系統會在一回合內連續按鍵，請多加利用以節省回合數。\n" \
                                      f"5. **控制在 5-10 回合結束**：驗證完這 1~2 個點後，**請立即宣告測試完畢並結束操作，並給出精確的 PASS/FAIL 結論**。整個任務請務必控制在 **5 ~ 10 回合內**完成。**"
                
                report_file.write(f"\n### 🔍 自動掃描焦點地圖\n已自動掃描整頁可聚焦元素，共發現 {len(focus_map)} 個元素，詳細焦點順序地圖已注入 AI 上下文中。\n")
                report_file.flush()
                
        # Level 3 Link Mapping Scan (若為 WCAG 指南任務，自動提取網站地圖注入給 AI，防止盲目點選)
        if args.wcag:
            try:
                print("[*] 正在提取網站同源頁面地圖以優化 AI 導航效率...")
                get_links_script = """
                (() => {
                    return Array.from(document.querySelectorAll('a[href]'))
                        .map(a => ({ text: a.textContent.trim(), href: a.href }))
                        .filter(item => {
                            try {
                                const url = new URL(item.href);
                                return url.host === window.location.host;
                            } catch(e) {
                                return false;
                            }
                        });
                })()
                """
                site_links = page.evaluate(get_links_script)
                # 去重
                unique_links = {}
                for item in site_links:
                    if item["href"] and item["href"].startswith("http"):
                        unique_links[item["href"]] = item["text"] or "無文字說明"
                
                if unique_links:
                    links_text = "\n".join([f"- {url} ({text})" for url, text in unique_links.items()])
                    extra_instructions += f"\n\n【網站同源子頁面網址地圖 (Site Map - URLs)】:\n{links_text}\n\n" \
                                          f"**【⚠️ 導航降本增效核心指示】**\n" \
                                          f"1. **直接 URL 導航**：上表列出了此網站內所有合法的內部頁面 URL。如果你需要巡檢或跳轉至其他子頁面，**請直接使用 `navigate` 工具載入對應網址**，絕對不要手動去點擊選單按鈕或尋找連結！這可以為您節省高達 90% 的時間與 Token 消耗。\n" \
                                          f"2. **外部網域已封鎖**：非上表 host 的外部連結已在瀏覽器層面被自動屏蔽，請不要嘗試訪問。"
                    print(f"[✓] 提取完成！已將 {len(unique_links)} 個同源子頁面 URL 注入 AI 上下文。")
            except Exception as e:
                print(f"[WARNING] 提取網站地圖失敗: {e}")

        # 初始已發現網頁字典 (用於地圖繪製與補完任務，記錄與維護每個頁面的狀態：{"url": {"title": "...", "fully_explored": bool}})
        discovered_pages = {}
        if args.generate_sitemap and args.sitemap and os.path.exists(args.sitemap):
            try:
                with open(args.sitemap, "r", encoding="utf-8") as sf:
                    raw_data = json.load(sf)
                    for item in raw_data:
                        if isinstance(item, str):
                            discovered_pages[item.strip()] = {"fully_explored": False, "title": ""}
                        elif isinstance(item, dict) and "url" in item:
                            url = item["url"].strip()
                            discovered_pages[url] = {
                                "fully_explored": item.get("fully_explored", False),
                                "title": item.get("title", "")
                            }
                print(f"[*] [COMPLETION] 成功從基底地圖檔載入 {len(discovered_pages)} 個網頁節點。")
            except Exception:
                pass
        
        initial_url = args.url or INITIAL_URL
        if initial_url not in discovered_pages:
            try:
                init_title = page.title()
            except Exception:
                init_title = ""
            discovered_pages[initial_url] = {"fully_explored": False, "title": init_title}

        # 若為地圖繪製任務，且有指定 sitemap 檔案，進行「地圖補完」任務提示詞組裝
        if args.generate_sitemap and args.sitemap and os.path.exists(args.sitemap):
            fully_explored_list = [u for u, info in discovered_pages.items() if info.get("fully_explored")]
            unexplored_list = [u for u, info in discovered_pages.items() if not info.get("fully_explored")]
            
            completion_prompt = (
                f"\n\n【🗺️ 網站地圖補完與探索任務說明】\n"
                f"目前我們已經掌握了網站中的以下頁面：\n"
            )
            if fully_explored_list:
                completion_prompt += f"- 🟢 已完全探明（無新子頁）的頁面：\n{json.dumps(fully_explored_list, indent=2, ensure_ascii=False)}\n"
            if unexplored_list:
                completion_prompt += f"- 🟡 待進一步探索（可能含有未探明子頁）的頁面：\n{json.dumps(unexplored_list, indent=2, ensure_ascii=False)}\n"
            
            completion_prompt += (
                f"\n請避開已完全探明的頁面，集中精力在待探索頁面上，點擊其中的選單、按鈕或連結來發現新的路由分頁。\n"
                f"結束時，請在您的最終回應中，輸出包含所有舊網址與新發現網址的完整地圖清單，格式為 JSON 物件陣列。範例：\n"
                f"[\n"
                f"  {{\n"
                f"    \"url\": \"http://192.168.1.1/dashboard\",\n"
                f"    \"title\": \"Dashboard\",\n"
                f"    \"fully_explored\": true\n"
                f"  }},\n"
                f"  {{\n"
                f"    \"url\": \"http://192.168.1.1/wan\",\n"
                f"    \"title\": \"WAN Settings\",\n"
                f"    \"fully_explored\": false\n"
                f"  }}\n"
                f"]\n"
                f"請將已完全點選完所有連結、無任何未探索子頁的頁面標記為 `\"fully_explored\": true`；其餘可能仍有未探索項目的標記為 `false`。"
            )
            user_task += completion_prompt
            print(f"[*] [SITEMAP COMPLETION] 已載入地圖補完基底，含 {len(fully_explored_list)} 個已完全探明、{len(unexplored_list)} 個待探索頁面。")

        # 建立第一次互動
        interaction = agent.create_initial_interaction(user_task, initial_screenshot, extra_instructions)
        
        # 紀錄 Token 消耗
        init_tokens = get_interaction_tokens(interaction)
        total_input_tokens += init_tokens["input"]
        total_output_tokens += init_tokens["output"]
        total_tokens += init_tokens["total"]
        print(f"[*] Initial Turn Token Usage - Input: {init_tokens['input']}, Output: {init_tokens['output']}, Total: {init_tokens['total']}")
            
        # AI 代理執行循環
        for turn in range(args.max_turns):
            print(f"\n{'='*60}")
            print(f"[TURN {turn + 1}/{args.max_turns}]")
            print(f"{'='*60}")
            
            report_file.write(f"## 🔄 第 {turn + 1} 回合 (Turn {turn + 1})\n")
            log_file.write(f"--- Turn {turn + 1} ---\n")
            
            # 提取並印出 AI 的文字回應（如果有的話，例如思考過程或中間說明）
            text_response = agent.extract_text_response(interaction)
            if text_response.strip():
                print(f"\n[AI] {text_response}")
                report_file.write(f"🤖 **AI 的思考與說明**:\n> {text_response}\n\n")
                log_file.write(f"AI: {text_response}\n")
            
            # 檢查是否有操作指令，若無則結束
            if not agent.has_function_calls(interaction):
                print("\n[OK] Task completed")
                report_file.write(f"✅ **任務已完成**：AI 未發送進一步的操作指令。\n\n")
                log_file.write("Task completed.\n")
                break
            
            # 執行操作
            report_file.write(f"⚙️ **執行的操作**:\n")
            for step in interaction.steps:
                if step.type == "function_call":
                    report_file.write(f"- **動作**: `{step.name}`\n")
                    report_file.write(f"  - **參數**: `{json.dumps(step.arguments, ensure_ascii=False)}`\n")
                    log_file.write(f"Command: {step.name}({json.dumps(step.arguments, ensure_ascii=False)})\n")
            report_file.flush()
            
            results = execute_function_calls(interaction, page, viewport_width, viewport_height)
            
            # 擷取執行後狀態
            function_responses = get_function_responses(page, results, interaction)
            
            # 拍照存檔用於報告
            post_screenshot = page.screenshot(type="png")
            if record_dir:
                screenshot_name = f"step_{turn + 1}_post.png"
                with open(os.path.join(record_dir, screenshot_name), "wb") as f:
                    f.write(post_screenshot)
            report_file.write(f"\n📸 **執行後畫面**:\n![步驟截圖]({screenshot_name if record_dir else ''})\n\n")
            report_file.flush()
            
            # 繼續對話
            interaction = agent.continue_interaction(interaction.id, function_responses)
            
            # 紀錄 Token 消耗
            turn_tokens = get_interaction_tokens(interaction)
            total_input_tokens += turn_tokens["input"]
            total_output_tokens += turn_tokens["output"]
            total_tokens += turn_tokens["total"]
            print(f"[*] Turn {turn + 1} Token Usage - Input: {turn_tokens['input']}, Output: {turn_tokens['output']}, Total: {turn_tokens['total']}")
            
            # 記錄當前頁面 URL 作為已發現頁面，確保即使崩潰或中斷也絕不漏掉任何走訪過的網頁
            curr_url = page.url
            if curr_url and curr_url not in discovered_pages:
                from urllib.parse import urlparse
                base_host = urlparse(args.url or INITIAL_URL).netloc
                if urlparse(curr_url).netloc == base_host:
                    try:
                        title = page.title()
                    except Exception:
                        title = ""
                    discovered_pages[curr_url] = {"fully_explored": False, "title": title}
        
        else:
            print(f"\n[!] Max turns reached ({args.max_turns})")
            report_file.write(f"⚠️ **已達到最大執行回合數** ({args.max_turns})。\n\n")
            
            # 當達到最大回合數時，發送最後一次對話獲取評估總結結論
            print("[*] Requesting final summary from AI due to max turns limit...")
            try:
                sum_res = agent.get_final_summary(interaction.id)
                summary = sum_res["summary"]
                total_input_tokens += sum_res["usage"]["input"]
                total_output_tokens += sum_res["usage"]["output"]
                total_tokens += sum_res["usage"]["total"]
                if summary.strip():
                    print(f"\n[AI 最終總結結論]\n{summary}\n")
                    report_file.write(f"🤖 **AI 最終評估總結結論**:\n{summary}\n\n")
                    log_file.write(f"AI Final Summary: {summary}\n")
            except Exception as summary_err:
                print(f"[!] Failed to get final summary from AI: {summary_err}")
        
        # 如果是生成網站地圖任務，在結束前進行地圖解析與存檔
        if args.generate_sitemap:
            print("\n[*] 偵測到網站地圖繪製任務，正在解析並儲存結果...")
            try:
                final_text = agent.extract_text_response(interaction)
            except Exception:
                final_text = ""
                
            # 若因達到最大回合數而有生成 summary，將其附加在 final_text 之後，防止地圖存在於總結中卻沒被抓到
            if 'summary' in locals() and summary:
                final_text += "\n" + summary
                
            # 整合並去重：AI 回傳清單 + 歷史走訪記錄 (discovered_pages)
            ai_discovered = {}
            if json_match:
                try:
                    parsed_items = json.loads(json_match.group(1))
                    if isinstance(parsed_items, list):
                        for item in parsed_items:
                            if isinstance(item, str):
                                ai_discovered[item.strip()] = {"fully_explored": False, "title": ""}
                            elif isinstance(item, dict) and "url" in item:
                                url = item["url"].strip()
                                ai_discovered[url] = {
                                    "fully_explored": item.get("fully_explored", False),
                                    "title": item.get("title", "")
                                }
                except Exception as json_err:
                    print(f"[WARNING] 無法使用物件 JSON 解析 AI 的地圖回覆: {json_err}")

            if not ai_discovered:
                # Fallback to regex text search
                from urllib.parse import urlparse
                base_host = urlparse(args.url or INITIAL_URL).netloc
                raw_urls = re.findall(r"(https?://[^\s`\"'()<>]+)", final_text)
                for ru in raw_urls:
                    clean_ru = ru.rstrip(".,;]}`\"')")
                    if urlparse(clean_ru).netloc == base_host:
                        ai_discovered[clean_ru] = {"fully_explored": False, "title": ""}

            # 合併 AI 回傳與走訪記錄
            for url, info in ai_discovered.items():
                if url not in discovered_pages:
                    discovered_pages[url] = info
                else:
                    # 如果 AI 有明確標註 fully_explored，以 AI 的標註為準
                    if info.get("fully_explored"):
                        discovered_pages[url]["fully_explored"] = True
                    if info.get("title") and not discovered_pages[url].get("title"):
                        discovered_pages[url]["title"] = info["title"]

            # 組裝最終寫入格式的 JSON List
            final_sitemap = []
            for url, info in discovered_pages.items():
                final_sitemap.append({
                    "url": url,
                    "title": info.get("title") or "",
                    "fully_explored": info.get("fully_explored", False)
                })

            if not final_sitemap:
                final_sitemap = [{
                    "url": args.url or INITIAL_URL,
                    "title": "Home",
                    "fully_explored": False
                }]
                
            os.makedirs("sitemaps", exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            sitemap_file_path = args.sitemap or f"sitemaps/sitemap_{timestamp}.json"
            
            try:
                with open(sitemap_file_path, "w", encoding="utf-8") as sf:
                    json.dump(final_sitemap, sf, indent=2, ensure_ascii=False)
                print(f"[✓] 網站地圖已成功繪製並儲存至: {sitemap_file_path}")
                print(f"    包含 {len(final_sitemap)} 個網頁節點")
                report_file.write(f"\n## 🗺️ 已成功繪製網站地圖\n已儲存至 `{sitemap_file_path}`，共包含 {len(final_sitemap)} 個網址分頁。\n\n")
                report_file.flush()
            except Exception as save_err:
                print(f"[ERROR] 儲存網站地圖檔案失敗: {save_err}")
                
        # 輸出 Token 統計與計費資訊至主控台、報告與日誌
        print_token_and_cost_summary(args.model, total_input_tokens, total_output_tokens, report_file)
        printed_token_summary = True
        
        log_file.write(f"\nTotal Token Usage - Input: {total_input_tokens}, Output: {total_output_tokens}, Total: {total_tokens}\n")
        log_file.flush()
        
        print(f"\n[-] Closing browser in {RESULT_OBSERVATION_TIME} seconds...")
        time.sleep(RESULT_OBSERVATION_TIME)

    except BaseException as e:
        if not isinstance(e, SystemExit) or e.code != 0:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            if 'report_file' in locals() and not report_file.closed:
                report_file.write(f"\n## ❌ 執行發生錯誤\n`{str(e)}`\n")

    finally:
        print("\n[~] Cleaning up...")
        # 確保不論中止、完成或出錯，都一定會計算與輸出 Token 消耗 (含 AI 登入消耗)
        if not printed_token_summary:
            try:
                # 優先使用自訂流程內局部變數 (total_input_tokens)，否則 fallback 到 main 的全域變數
                input_toks = locals().get('total_input_tokens', global_total_input_tokens)
                output_toks = locals().get('total_output_tokens', global_total_output_tokens)
                
                if input_toks > 0 or output_toks > 0:
                    rf_target = locals().get('report_file')
                    if rf_target and rf_target.closed:
                        rf_target = None
                    print_token_and_cost_summary(args.model, input_toks, output_toks, rf_target)
            except Exception as billing_err:
                print(f"[WARNING] 無法輸出最終 Token 消耗結算: {billing_err}")

        if 'report_file' in locals() and not report_file.closed:
            report_file.close()
        if 'log_file' in locals() and not log_file.closed:
            log_file.close()
        browser.close()
        playwright.stop()
        print("[✓] Done.\n")


if __name__ == "__main__":
    main()
