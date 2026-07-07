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
    if args.task:
        user_task = args.task
    elif args.content:
        user_task = " ".join(args.content)
    else:
        user_task = DEFAULT_TASK
        
    extra_instructions = ""
    if args.wcag:
        filename = f"guideline_{args.wcag.replace('.', '_')}.md"
        filepath = os.path.join("documentation", "wcag_rules", filename)
        if os.path.exists(filepath):
            print(f"[*] Loading WCAG 2.2 rules from: {filepath}")
            with open(filepath, "r", encoding="utf-8") as f:
                rules_content = f.read()
            extra_instructions = f"\n\n請務必依據以下 WCAG 2.2 規範進行驗證及操作：\n\n{rules_content}"
        else:
            print(f"[WARNING] WCAG rules file {filepath} not found. Running without injected rules.")
            
    # 進行 Axe-core 適用度評估（AI 自動確認是否只需 Axe-core 代碼檢測解決）
    is_axe_only, axe_reason = check_task_suitability_for_axe(user_task, extra_instructions, args.model)
    if is_axe_only:
        print("\n" + "="*60)
        print("🎯 AI 評估：此任務只需透過 Axe-core (代碼審查) 即可解決！")
        print(f"  原因說明：{axe_reason}")
        print("="*60)
        print("[*] 啟動 Axe-core 本地自動化無障礙檢測引擎...")
        
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1024, "height": 768}
        )
        page = context.new_page()
        
        target_url = args.url or INITIAL_URL
        print(f"[>>] 正在導航至目標頁面: {target_url}")
        try:
            page.goto(target_url, wait_until="domcontentloaded")
            print("[+] 正在提取網頁 DOM 結構進行無障礙審查...")
            
            axe_results = run_axe_audit(page)
            violations = axe_results.get("violations", [])
            
            print(f"[✓] 本地代碼檢測完成！共發現 {len(violations)} 個無障礙違規項目。")
            print("="*60)
            
            report_lines = []
            report_lines.append("# 📝 Axe-core 無障礙靜態審查報告\n")
            report_lines.append(f"- **檢測目標網址**: {target_url}")
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
                    
                    header = f"### {idx+1}. [{impact}] {vio_id} - {help_msg}"
                    report_lines.append(header)
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
                        
                        node_text = f"  - 節點 {node_idx+1}: `{selector}`"
                        report_lines.append(node_text)
                        report_lines.append(f"    - HTML: `{html_snippet}`")
                        report_lines.append(f"    - 修復建議: {summary}")
                        
                        if node_idx == 0:
                            print(f"   - 範例節點: {selector}")
                            print(f"     範例 HTML: {html_snippet}")
                            print(f"     修復建議: {summary}")
                            
                    if len(nodes) > 5:
                        report_lines.append(f"  - *(其餘 {len(nodes) - 5} 個節點已省略)*")
                    report_lines.append("")
                    
            if args.record:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                record_dir = os.path.join("records", f"axe_run_{timestamp}")
                os.makedirs(record_dir, exist_ok=True)
                
                report_path = os.path.join(record_dir, "report.md")
                with open(report_path, "w", encoding="utf-8") as rf:
                    rf.write("\n".join(report_lines))
                    
                json_path = os.path.join(record_dir, "axe_raw_results.json")
                with open(json_path, "w", encoding="utf-8") as jf:
                    json.dump(axe_results, jf, indent=2, ensure_ascii=False)
                    
                print(f"\n[*] 審查報告已儲存至: {record_dir}")
                
            print("="*60 + "\n")
            
        except Exception as e:
            print(f"[ERROR] Axe-core 執行失敗: {e}")
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

    # 初始化 Token 累計變數
    total_input_tokens = 0
    total_output_tokens = 0
    total_tokens = 0

    try:
        # 前往初始頁面
        print(f"[>>] Navigating to: {args.url}")
        print("[+] Capturing screen...")
        page.goto(args.url)
        try:
            page.focus("body")
        except Exception:
            pass
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
                extra_instructions += f"\n\n{focus_map_text}\n\n**請注意：上表為本地直接對所有 DOM 元素進行 focus() 後所得的資料。如果上表中有任何互動元素沒有顯示有效的 outline（即 outline-style 為 none），或者某些應有的元素不在上表中（無法被 Tab 聚焦），這代表可能違反 WCAG 2.4.7 (Focus Visible) 或 2.1.1 (Keyboard)。請優先參照上表的坐標與順序來規劃您的驗證操作。**"
                
                report_file.write(f"\n### 🔍 自動掃描焦點地圖\n已自動掃描整頁可聚焦元素，共發現 {len(focus_map)} 個元素，詳細焦點順序地圖已注入 AI 上下文中。\n")
                report_file.flush()
                
        # 建立第一次互動
        print(f"[AI] Sending task to {'Claude' if is_claude else 'Gemini'}...")
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
            if record_dir:
                screenshot_name = f"step_{turn + 1}_post.png"
                with open(os.path.join(record_dir, screenshot_name), "wb") as f:
                    f.write(post_screenshot)
            report_file.write(f"\n📸 **執行後畫面**:\n![步驟截圖]({screenshot_name if record_dir else ''})\n\n")
            report_file.flush()
            
            # 繼續對話
            print(f"[AI] Sending results to {'Claude' if is_claude else 'Gemini'}...")
            interaction = agent.continue_interaction(interaction.id, function_responses)
            
            # 紀錄 Token 消耗
            turn_tokens = get_interaction_tokens(interaction)
            total_input_tokens += turn_tokens["input"]
            total_output_tokens += turn_tokens["output"]
            total_tokens += turn_tokens["total"]
            print(f"[*] Turn {turn + 1} Token Usage - Input: {turn_tokens['input']}, Output: {turn_tokens['output']}, Total: {turn_tokens['total']}")
        
        else:
            print(f"\n[!] Max turns reached ({args.max_turns})")
            report_file.write(f"⚠️ **已達到最大執行回合數** ({args.max_turns})。\n\n")
        
        # 輸出 Token 統計與計費資訊至主控台、報告與日誌
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
        
        model_name_norm = args.model.lower().replace("-", ".").replace("_", ".")
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
        usd_input_cost = (total_input_tokens / 1000000.0) * rates["input"]
        usd_output_cost = (total_output_tokens / 1000000.0) * rates["output"]
        total_usd_cost = usd_input_cost + usd_output_cost
        
        EXCHANGE_RATE_TWD = 32.5
        total_twd_cost = total_usd_cost * EXCHANGE_RATE_TWD
        
        token_summary = (
            f"\n{'='*60}\n"
            f"💰 Token 消耗與花費統計 (Token Usage & Cost Summary)\n"
            f"{'='*60}\n"
            f"  輸入 Token (Input Tokens)  : {total_input_tokens:,}\n"
            f"  輸出 Token (Output Tokens) : {total_output_tokens:,}\n"
            f"  總計 Token (Total Tokens)  : {total_tokens:,}\n"
            f"{'-'*60}\n"
            f"  計費模型 (Pricing Model)   : {model_key} (輸入: ${rates['input']:.2f}/M, 輸出: ${rates['output']:.2f}/M)\n"
            f"  預估花費 (Estimated Cost)  : ${total_usd_cost:.5f} USD\n"
            f"  折合台幣 (Converted Cost)  : NT$ {total_twd_cost:.3f} TWD (匯率: {EXCHANGE_RATE_TWD})\n"
            f"{'-'*60}\n"
            f"  * 註記：此費用係以 2026/07/07 官方公開標價計算，僅供參考\n"
            f"{'='*60}\n"
        )
        print(token_summary)
        
        report_file.write(f"## 💰 Token 消耗與花費統計\n\n")
        report_file.write(f"- **輸入 Token 數 (Input Tokens)**: `{total_input_tokens:,}`\n")
        report_file.write(f"- **輸出 Token 數 (Output Tokens)**: `{total_output_tokens:,}`\n")
        report_file.write(f"- **總計 Token 數 (Total Tokens)**: `{total_tokens:,}`\n")
        report_file.write(f"- **計費模型 (Pricing Model)**: `{model_key}` (輸入: ${rates['input']:.2f}/M, 輸出: ${rates['output']:.2f}/M)\n")
        report_file.write(f"- **預估美金花費 (Estimated USD)**: `${total_usd_cost:.5f} USD`\n")
        report_file.write(f"- **預估台幣花費 (Estimated TWD)**: `NT$ {total_twd_cost:.3f} TWD` (匯率: {EXCHANGE_RATE_TWD})\n")
        report_file.write(f"- *註記：此費用係以 2026/07/07 官方公開標價計算，僅供參考*\n\n")
        report_file.flush()
        
        log_file.write(f"\nTotal Token Usage - Input: {total_input_tokens}, Output: {total_output_tokens}, Total: {total_tokens}\n")
        log_file.write(f"Total Cost - USD: {total_usd_cost:.5f}, TWD: {total_twd_cost:.3f}\n")
        log_file.flush()
        
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
