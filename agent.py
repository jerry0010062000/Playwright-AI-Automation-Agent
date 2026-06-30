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
from playwright.sync_api import sync_playwright

# 解決 Windows 主控台編碼問題，確保能正確輸出 UTF-8 字元
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


from config import (
    GEMINI_API_KEY, CLAUDE_API_KEY,
    SCREEN_WIDTH, SCREEN_HEIGHT, MAX_TURNS, HEADLESS,
    RESULT_OBSERVATION_TIME, MODEL_NAME, DEFAULT_TASK,
    INITIAL_URL, AI_ROLE, AI_BEHAVIOR, OUTPUT_FORMAT,
    TOOL_TYPE, TOOL_ENVIRONMENT, ENABLE_PROMPT_INJECTION_DETECTION
)
from gemini_client import GeminiAgent, get_function_responses
from claude_client import ClaudeAgent
from browser_actions import execute_function_calls


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
                       help=f'AI 角色類型。default=通用, tester=測試, scraper=資料收集, shopper=購物, researcher=研究。預設：{AI_ROLE}')
    
    parser.add_argument('-b', '--behavior', type=str,
                       choices=['careful', 'fast', 'verbose', 'silent'],
                       default=AI_BEHAVIOR,
                       help=f'行為模式。careful=謹慎慢速, fast=快速執行, verbose=詳細輸出, silent=最少輸出。預設：{AI_BEHAVIOR}')

    parser.add_argument('-o', '--output', type=str,
                       choices=['natural', 'json', 'list', 'table'],
                       default=OUTPUT_FORMAT,
                       help=f'輸出格式。natural=自然語言, json=JSON 格式, list=列表, table=表格。預設：{OUTPUT_FORMAT}')
    
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
    
    return parser.parse_args()


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
    if args.task:
        user_task = args.task
    elif args.content:
        user_task = " ".join(args.content)
    else:
        user_task = DEFAULT_TASK
    
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

    # 建立臨時記錄資料夾與報告
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    record_dir = os.path.join("records", f"run_{timestamp}")
    os.makedirs(record_dir, exist_ok=True)
    print(f"[*] Recording this run to: {record_dir}")
    
    report_path = os.path.join(record_dir, "report.md")
    log_path = os.path.join(record_dir, "run.log")
    
    report_file = open(report_path, "w", encoding="utf-8")
    log_file = open(log_path, "w", encoding="utf-8")
    
    report_file.write(f"# AI Playwright Agent 執行報告\n\n")
    report_file.write(f"- **時間戳記**: `{timestamp}`\n")
    report_file.write(f"- **任務內容**: {user_task}\n")
    report_file.write(f"- **AI 模型**: `{args.model}`\n")
    report_file.write(f"- **模擬裝置**: `{args.device}`\n")
    report_file.write(f"- **初始網址**: `{args.url}`\n\n")
    report_file.flush()

    try:
        # 前往初始頁面
        print(f"[>>] Navigating to: {args.url}")
        print("[+] Capturing screen...")
        page.goto(args.url)
        initial_screenshot = page.screenshot(type="png")
        
        # 儲存初始截圖
        initial_screenshot_name = "step_0_initial.png"
        with open(os.path.join(record_dir, initial_screenshot_name), "wb") as f:
            f.write(initial_screenshot)
        report_file.write(f"## 🎬 初始狀態\n")
        report_file.write(f"已導航至 {args.url}，初始畫面如下：\n\n")
        report_file.write(f"![初始截圖]({initial_screenshot_name})\n\n")
        report_file.flush()
        
        # 建立第一次互動
        print(f"[AI] Sending task to {'Claude' if is_claude else 'Gemini'}...")
        interaction = agent.create_initial_interaction(user_task, initial_screenshot)
        
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
            print("\n[>] Executing AI commands...")
            report_file.write(f"⚙️ **執行的操作**:\n")
            for step in interaction.steps:
                if step.type == "function_call":
                    report_file.write(f"- **動作**: `{step.name}`\n")
                    report_file.write(f"  - **參數**: `{json.dumps(step.arguments, ensure_ascii=False)}`\n")
                    log_file.write(f"Command: {step.name}({json.dumps(step.arguments, ensure_ascii=False)})\n")
            report_file.flush()
            
            results = execute_function_calls(interaction, page, viewport_width, viewport_height)
            
            # 擷取執行後狀態
            print("[+] Capturing screen...")
            function_responses = get_function_responses(page, results, interaction)
            
            # 拍照存檔用於報告
            post_screenshot = page.screenshot(type="png")
            screenshot_name = f"step_{turn + 1}_post.png"
            with open(os.path.join(record_dir, screenshot_name), "wb") as f:
                f.write(post_screenshot)
            report_file.write(f"\n📸 **執行後畫面**:\n![步驟截圖]({screenshot_name})\n\n")
            report_file.flush()
            
            # 繼續對話
            print(f"[AI] Sending results to {'Claude' if is_claude else 'Gemini'}...")
            interaction = agent.continue_interaction(interaction.id, function_responses)
        
        else:
            print(f"\n[!] Max turns reached ({args.max_turns})")
            report_file.write(f"⚠️ **已達到最大執行回合數** ({args.max_turns})。\n\n")
        
        print(f"\n[-] Closing browser in {RESULT_OBSERVATION_TIME} seconds...")
        time.sleep(RESULT_OBSERVATION_TIME)

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        if 'report_file' in locals() and not report_file.closed:
            report_file.write(f"\n## ❌ 執行發生錯誤\n`{str(e)}`\n")

    finally:
        print("\n[~] Cleaning up...")
        if 'report_file' in locals() and not report_file.closed:
            report_file.close()
        if 'log_file' in locals() and not log_file.closed:
            log_file.close()
        browser.close()
        playwright.stop()
        print("[✓] Done.\n")


if __name__ == "__main__":
    main()
