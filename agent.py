"""
Claude + Playwright 自動化無障礙巡檢代理程式
使用 Anthropic Claude Computer Use API 自動操作瀏覽器進行 WCAG 2.2 / Axe-core 審查

使用方法：
  基本：python agent.py "你的任務"
  進階：python agent.py -m claude-sonnet-5 --wcag 2.1 "無障礙檢測"
  幫助：python agent.py --help
"""

import sys
import os
import datetime
import json
import re
import time
import argparse
import urllib.parse
from urllib.parse import urlparse, urljoin
from playwright.sync_api import sync_playwright

import config
from config import (
    CLAUDE_API_KEY, CLAUDE_BASE_URL, CLAUDE_AUTH_TOKEN, CLAUDE_USE_GATEWAY,
    SCREEN_WIDTH, SCREEN_HEIGHT, MAX_TURNS, HEADLESS,
    RESULT_OBSERVATION_TIME, MODEL_NAME, DEFAULT_TASK,
    INITIAL_URL, AI_ROLE, AI_BEHAVIOR, OUTPUT_FORMAT,
    TOOL_TYPE, TOOL_ENVIRONMENT, ENABLE_PROMPT_INJECTION_DETECTION,
    MAX_CRAWL_PAGES, MAX_LOGIN_TURNS,
    AUTO_LOGIN_USERNAME, AUTO_LOGIN_PASSWORD
)
from claude_client import ClaudeAgent, get_function_responses
from browser_actions import execute_function_calls, run_axe_audit, scan_focus_path
from core.sitemap_engine import (
    mark_dynamic_verified,
    build_wcag_coverage_table,
    restructure_sitemap_hierarchy,
    verify_and_sync_sitemap
)
from core.login_engine import perform_ai_login_phase, handle_auto_login
from core.static_audit import (
    perform_local_site_audit,
    check_task_suitability_for_axe,
    is_wcag_guideline_static,
    get_violation_wcag_level,
    get_wcag_conformance_level
)
from core.prompt_builder import (
    print_token_and_cost_summary,
    build_wcag_prompt,
    get_interaction_tokens
)
from reporting.single_page_report import (
    get_map_records_dir,
    get_page_report_relpath,
    dump_single_page_settlement_report
)

# 解決 Windows 主控台編碼問題，確保能正確輸出 UTF-8 字元
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


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
        return False


def parse_arguments():
    """解析命令列參數"""
    parser = argparse.ArgumentParser(
        description='[CLAUDE-AGENT] Playwright 自動化代理 - AI 瀏覽器控制與無障礙檢測系統',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
[USAGE] 使用範例：
  基本用法：
    python agent.py "搜尋 Python 教學"
    python agent.py "前往 GitHub 並登入"
  
  指定模型：
    python agent.py -m claude-sonnet-5 "搜尋資料"
    python agent.py -m claude-3-5-sonnet-20241022 "執行測試"
  
  指定初始網址：
    python agent.py --url https://www.bing.com "搜尋資料"
    python agent.py --url http://localhost:8000 "測試本地網站"
  
  指定無障礙 WCAG 指南檢測：
    python agent.py --url http://localhost:8000 --wcag 2.1 "全站無障礙巡檢"
    python agent.py --url http://localhost:8000 --wcag all "靜態無障礙全量掃描"
  
  指定要模擬的裝置類型：
    桌上型瀏覽器 (Desktop)： python agent.py -d desktop "測試網站"
    手機版 (Mobile)：        python agent.py -d mobile "測試網站"
    平板版 (Tablet)：        python agent.py -d tablet "測試網站"
  
  組合參數：
    python agent.py -m claude-sonnet-5 -r tester -b careful "完整測試"
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
                       help=f'指定 Claude 模型。可用：claude-sonnet-5, claude-3-5-sonnet-20241022 等。預設：{MODEL_NAME}')
    
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
                       help='指定 WCAG 規範版本（如 2.1, 2.2 或 2.0），啟用無障礙專家提示與報告系統')
    
    parser.add_argument('--record', action='store_true', default=False,
                       help='啟用詳細日誌記錄與報告產出。記錄將儲存於 records/ 目錄中')
    
    parser.add_argument('--sitemap', type=str, default=None,
                       help='指定 Site Map JSON 檔案路徑。若指定，程式將進入「系統導航 (Feeder)」模式，自動化依序審查地圖中的受控頁面。若標記為 verify 則自動探索。')
    
    parser.add_argument('--verify-sitemap', action='store_true', default=False,
                       help='啟動地圖探索與校對引擎：自動發現新頁面、校對狀態碼、標題，並同步更新 JSON 地圖檔案。若地圖不存在會自動創建。')
    
    parser.add_argument('--single-page', action='store_true', default=False,
                       help='強制單網頁審查模式，即便指定了 sitemap 檔也僅掃描初始網址，用以支援地圖記錄存檔與單頁報告生成。')
    
    parser.add_argument('--username', type=str, default=None,
                       help='自訂登入帳號，覆蓋 config.py 中的預設值')
    parser.add_argument('--password', type=str, default=None,
                       help='自訂登入密碼，覆蓋 config.py 中的預設值')
    parser.add_argument('--rigor', type=str,
                       choices=['balanced', 'strict', 'fast'],
                       default='balanced',
                       help='指定動態巡檢嚴謹度策略。balanced=均衡推薦(關鍵節點截圖), strict=精準細緻(每步存證截圖), fast=極速低耗(批次走訪/僅違規截圖)。預設：balanced')
    
    return parser.parse_args()


def run_agent_workflow(args):
    """主控執行流程核心"""
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
    global_total_input_tokens = 0
    global_total_output_tokens = 0
    global_total_cache_read_tokens = 0
    global_total_cache_creation_tokens = 0
    printed_token_summary = False
    
    if args.wcag:
        filename = f"guideline_{args.wcag.replace('.', '_')}.md"
        filepath = os.path.join("documentation", "wcag_rules", filename)
        if os.path.exists(filepath):
            print(f"[*] 載入 WCAG 2.2 規範文檔: {filepath}")
            with open(filepath, "r", encoding="utf-8") as f:
                rules_content = f.read()
            extra_instructions = f"\n\n請務必依據以下 WCAG 2.2 規範進行驗證及操作：\n\n{rules_content}\n\n" \
                                 f"**【⚠️ 核心無障礙審查操作指引 - 避免無意義消耗】**\n" \
                                 f"1. **審查範圍與限制**：審查的預設範圍為「整個網站」（當前 Host 下的所有內部頁面）。如果頁面中包含連結至其他獨立網站的「外部連結」（即 Host 不同的網址），請**絕對不要點擊或進行處理**，外部連結不在審查範圍內。\n" \
                                 f"2. **快速判定不適用 (N/A) 原則**：請先使用專屬工具 `evaluate_javascript` 查詢當前頁面或點擊導航至其他內部子頁面。如果在整個網站的所有內部頁面上，完全沒有任何與該 WCAG 指南相關的 HTML 元素或組件（例如對於 Guideline 1.2 時基媒體，若整個網站根本沒有任何 `<audio>`、`<video>` 元素、`<iframe>` 嵌入影片或多媒體播放器），請在巡檢完內部頁面後結束任務，回報「該網站不包含任何相關媒體元素，此指南不適用（PASS / N/A）」。請有條理地進行內部子頁面導航，避免重覆訪問相同頁面。\n" \
                                 f"3. **禁止無效的系統嘗試**：請勿試圖按 F12、Ctrl+Shift+I 或以滑鼠右鍵開啟瀏覽器開發者工具（DevTools），也不要嘗試在地址欄輸入 `javascript:` 偽協定或使用 `data:` URL，這些在沙盒瀏覽器中均被安全機制封鎖或無法顯示。請直接使用專屬工具 `evaluate_javascript` 來讀取 DOM、或使用 `run_axe_audit` 進行無障礙代碼檢測。\n" \
                                 f"4. **【💡 全站高效率掃描技巧】**：若要快速檢查整個網站的所有頁面是否包含特定標籤（如 `<audio>`、`<video>`、`<iframe>` 等），您不需要逐頁點擊與等待，可在首頁直接執行非同步 fetch 掃描所有內部連結的 HTML。這可以讓您在 1 回合內檢測完所有子頁面，省去手動逐頁 Navigate 與等待的時間！"
        else:
            print(f"[WARNING] 未找到 WCAG 規範檔案 ({filepath})，將在無預載細則模式下執行。")
            
    # 進行適用度評估：若有 WCAG 指南，優先套用 rule-based 靜態與動態判定，免去 AI 評估成本
    is_axe_only = False
    axe_reason = ""
    if args.verify_sitemap:
        is_axe_only = True
        axe_reason = "啟動地圖探索與校對任務 (不需 AI 模型介入)"
    elif args.wcag:
        if is_wcag_guideline_static(args.wcag):
            is_axe_only = True
            axe_reason = f"WCAG {args.wcag} 為靜態可檢測指南，已套用本地自動化全站巡檢引擎。"
        else:
            is_axe_only = False
            axe_reason = f"WCAG {args.wcag} 為動態互動指南，需要視覺與鍵盤互動，啟動 AI 巡檢。"
    else:
        # 非 WCAG 指南任務，再由輕量級 AI 判定是否為 Axe 靜態任務
        is_axe_only, axe_wcag_ver, axe_reason = check_task_suitability_for_axe(user_task, extra_instructions, args.model)

    if is_axe_only:
        print("\n" + "="*60)
        print("[任務評估] 此任務可透過本地代碼與結構巡檢解決！")
        print(f"  原因說明：{axe_reason}")
        print("="*60)
        print("[*] 啟動本地自動化無障礙檢測引擎...")
        record_dir = None
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=args.headless)
        context = browser.new_context(
            viewport={"width": 1024, "height": 768}
        )
        page = context.new_page()
        page.add_init_script("window.addEventListener('contextmenu', e => e.preventDefault(), true);")
        
        target_url = args.url or INITIAL_URL
        print(f"[頁面導航] 正在導航至目標頁面: {target_url}")
        try:
            page.goto(target_url, wait_until="domcontentloaded")
            
            # 若配置了自動登入資訊，則在爬取前執行 AI 預先登入
            login_user = args.username if args.username is not None else AUTO_LOGIN_USERNAME
            login_pass = args.password if args.password is not None else AUTO_LOGIN_PASSWORD
            if login_user or login_pass:
                login_toks = perform_ai_login_phase(page, args.model, login_user, login_pass)
                global_total_input_tokens += login_toks.get("input", 0)
                global_total_output_tokens += login_toks.get("output", 0)
                global_total_cache_read_tokens += login_toks.get("cache_read_input_tokens", 0)
                global_total_cache_creation_tokens += login_toks.get("cache_creation_input_tokens", 0)
                if login_toks.get("success") is False:
                    print("\n[AI 預登入] [ERROR] 預先登入認證失敗！無法獲取後台授權，終止後續任務。\n")
                    if global_total_input_tokens > 0 or global_total_output_tokens > 0:
                        print_token_and_cost_summary(args.model, global_total_input_tokens, global_total_output_tokens, None, global_total_cache_read_tokens, global_total_cache_creation_tokens)
                        printed_token_summary = True
                    return
            
            # 執行地圖動態校對與更新引擎 (若開啟 --verify-sitemap)
            if args.verify_sitemap:
                sitemap_target = args.sitemap if args.sitemap else os.path.join("sitemaps", "sitemap.json")
                sitemap_res = verify_and_sync_sitemap(
                    page=page, 
                    base_url=target_url, 
                    sitemap_path=sitemap_target, 
                    max_pages=None,
                    model_name=args.model,
                    username=login_user,
                    password=login_pass
                )
                if sitemap_res and "tokens" in sitemap_res:
                    toks = sitemap_res["tokens"]
                    global_total_input_tokens += toks.get("input", 0)
                    global_total_output_tokens += toks.get("output", 0)
                    global_total_cache_read_tokens += toks.get("cache_read_input_tokens", 0)
                    global_total_cache_creation_tokens += toks.get("cache_creation_input_tokens", 0)
                
                # 若探索過程中有產生 AI 登入 Token，輸出結算
                if global_total_input_tokens > 0 or global_total_output_tokens > 0:
                    print_token_and_cost_summary(args.model, global_total_input_tokens, global_total_output_tokens, None, global_total_cache_read_tokens, global_total_cache_creation_tokens)
                    printed_token_summary = True
                return

            # 建立報告內容與檔名
            report_lines = []
            raw_results = {}
            
            if args.wcag:
                # 執行本地全站自動巡檢
                audit_res = perform_local_site_audit(page, target_url, args.wcag, sitemap_path=args.sitemap)
                total_violations = audit_res["total_violations"]
                
                print(f"[OK] 本地全站巡檢完成！共發現 {total_violations} 個無障礙違規項目。")
                print("="*60)
                
                conformance_level = get_wcag_conformance_level(args.wcag)
                report_lines.append(f"# WCAG {args.wcag} 本地自動化無障礙全站巡檢報告\n")
                report_lines.append(f"- **WCAG 檢測章節**: `WCAG {args.wcag}` ({conformance_level})")
                report_lines.append(f"- **檢測目標主頁**: {target_url}")
                report_lines.append(f"- **檢測時間**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                report_lines.append(f"- **巡檢子頁面總數**: {len(audit_res['results'])}")
                report_lines.append(f"- **發現違規項目總數**: {total_violations}\n")
                
                # 插入涵蓋條款與 Success Criteria 細分表格
                report_lines.extend(build_wcag_coverage_table(args.wcag))
                
                # 統計違規等級
                level_counts = {"A": 0, "AA": 0, "AAA": 0, "N/A": 0}
                for page_url, info in audit_res["results"].items():
                    for vio in info.get("violations", []):
                        wcag_level = get_violation_wcag_level(vio.get("tags", []))
                        level_counts[wcag_level] += 1
                
                report_lines.append("### 違規等級統計 (Violations by Level)")
                report_lines.append(f"- **Level A (必須達成)**: `{level_counts['A']}` 處違規")
                report_lines.append(f"- **Level AA (推薦達成)**: `{level_counts['AA']}` 處違規")
                report_lines.append(f"- **Level AAA (選配達成)**: `{level_counts['AAA']}` 處違規\n")
                
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
                            
                            wcag_level = get_violation_wcag_level(vio.get("tags", []))
                            level_str = f" (Level {wcag_level})" if wcag_level != "N/A" else ""
                            
                            report_lines.append(f"#### {idx+1}. [{impact}] {vio_id} - {help_msg}{level_str}")
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
                except Exception:
                    pass
                print(f"    - 頁面標題: '{title}'")
                print(f"    - HTML 大小: {html_len} bytes, DOM 元素數: {elements_count}")
                
                axe_results = run_axe_audit(page)
                violations = axe_results.get("violations", [])
                
                print(f"[✓] 本地代碼檢測完成！共發現 {len(violations)} 個無障礙違規項目。")
                print("="*60)
                
                level_counts = {"A": 0, "AA": 0, "AAA": 0, "N/A": 0}
                for vio in violations:
                    wcag_level = get_violation_wcag_level(vio.get("tags", []))
                    level_counts[wcag_level] += 1
                
                report_lines.append("# 📝 Axe-core 無障礙靜態審查報告\n")
                if args.wcag:
                    conformance_level = get_wcag_conformance_level(args.wcag)
                    report_lines.append(f"- **WCAG 檢測章節**: `WCAG {args.wcag}` ({conformance_level})")
                report_lines.append(f"- **檢測目標網址**: {target_url}")
                report_lines.append(f"- **頁面標題**: {title}")
                report_lines.append(f"- **DOM 元素數**: {elements_count}")
                report_lines.append(f"- **檢測時間**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                report_lines.append(f"- **違規項目總數**: {len(violations)}\n")
                
                report_lines.append("### 📊 違規等級統計 (Violations by Level)")
                report_lines.append(f"- **Level A (必須達成)**: `{level_counts['A']}` 處違規")
                report_lines.append(f"- **Level AA (推薦達成)**: `{level_counts['AA']}` 處違規")
                report_lines.append(f"- **Level AAA (選配達成)**: `{level_counts['AAA']}` 處違規\n")
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
                        
                        wcag_level = get_violation_wcag_level(vio.get("tags", []))
                        level_str = f" (Level {wcag_level})" if wcag_level != "N/A" else ""
                        
                        report_lines.append(f"### {idx+1}. [{impact}] {vio_id} - {help_msg}{level_str}")
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
            has_key = bool(CLAUDE_API_KEY or CLAUDE_AUTH_TOKEN or CLAUDE_BASE_URL or CLAUDE_USE_GATEWAY)
            
            if has_key:
                print("\n[AI] 正在將本地檢測結果遞交給 AI 進行智慧診斷與評估...")
                try:
                    summary_for_ai = []
                    summary_for_ai.append("【WCAG 2.2 官方涵蓋條款與 3 位數 Success Criteria 對照基準】:")
                    summary_for_ai.extend(build_wcag_coverage_table(args.wcag))
                    summary_for_ai.append("\n【實測 Axe-core 違規數據】:")
                    
                    if "results" in raw_results:
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
                    else:
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
                    
                    ai_agent = ClaudeAgent(role=args.role, behavior=args.behavior, output_format=args.output, model=args.model)
                    
                    ai_response = ai_agent.diagnose_static_audit(target_url, ai_data_text, screenshot_bytes, wcag_guideline=args.wcag)
                    ai_text = ai_response["text"]
                    ai_usage = ai_response["usage"]
                    global_total_input_tokens += ai_usage.get("input", 0)
                    global_total_output_tokens += ai_usage.get("output", 0)
                    global_total_cache_read_tokens += ai_usage.get("cache_read_input_tokens", 0)
                    global_total_cache_creation_tokens += ai_usage.get("cache_creation_input_tokens", 0)
                    
                    print("\n" + "="*60)
                    print("[AI 智慧診斷與評估報告]")
                    print("="*60)
                    print(ai_text)
                    print("="*60 + "\n")
                    
                    report_lines.append("\n" + "---" + "\n")
                    report_lines.append("## AI 智慧診斷與評估報告\n")
                    report_lines.append(ai_text)
                    
                    print_token_and_cost_summary(args.model, global_total_input_tokens, global_total_output_tokens, report_lines, global_total_cache_read_tokens, global_total_cache_creation_tokens)
                    printed_token_summary = True
                    
                except Exception as ai_err:
                    print(f"[WARNING] AI 智慧診斷調用失敗: {ai_err}")
            else:
                print("[INFO] 未偵測到對應的 API Key，跳過 AI 智慧診斷。")
                if global_total_input_tokens > 0 or global_total_output_tokens > 0:
                    print_token_and_cost_summary(args.model, global_total_input_tokens, global_total_output_tokens, report_lines, global_total_cache_read_tokens, global_total_cache_creation_tokens)
                    printed_token_summary = True

            if args.record:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                wcag_suffix = f"_wcag{args.wcag.replace('.', '_')}" if args.wcag else ""
                sitemap_tag = ""
                if args.sitemap:
                    sm_base = os.path.basename(args.sitemap)
                    sm_name = os.path.splitext(sm_base)[0]
                    sitemap_tag = f"_{sm_name}"
                record_dir = os.path.join("records", f"axe_run{sitemap_tag}{wcag_suffix}_{timestamp}")
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
    
    # 檢查 API 金鑰或 Proxy/Gateway 代理配置
    has_auth = bool(CLAUDE_API_KEY or CLAUDE_AUTH_TOKEN or CLAUDE_BASE_URL or CLAUDE_USE_GATEWAY)
    if not has_auth:
        print("[ERROR] 找不到 Claude API 金鑰或 Proxy/Gateway 代理配置！")
        print("[INFO] 請設定環境變數: $env:CLAUDE_API_KEY = 'your-api-key'")
        print("[INFO] 或在 config_llm.py 中設定: CLAUDE_API_KEY = '...' / CLAUDE_BASE_URL = '...' / CLAUDE_AUTH_TOKEN = '...'")
        return
        
    if not is_claude:
        print(f"[WARNING] 偵測到非 Claude 模型 '{args.model}'，將使用預設 Claude 代理。")
        args.model = "claude-3-5-sonnet-20241022"
        is_claude = True
    
    # 初始化 AI 代理
    agent = ClaudeAgent(
        role=args.role,
        behavior=args.behavior,
        output_format=args.output,
        model=args.model
    )
    
    # 啟動瀏覽器
    print("=" * 60)
    print(f"[CLAUDE-AGENT] Playwright Automation System")
    print("=" * 60)
    print(f"\n[TASK]   {user_task}")
    print(f"[MODEL]  {args.model}")
    print(f"[ROLE]   {args.role}")
    print(f"[MODE]   {args.behavior}")
    print(f"[FORMAT] {args.output}\n")
    print("[*] Launching browser...")
    
    playwright = sync_playwright().start()
    
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
        viewport_width = 1024 if is_claude else SCREEN_WIDTH
        viewport_height = 768 if is_claude else SCREEN_HEIGHT

    browser = playwright.chromium.launch(headless=args.headless)
    
    if args.device in ("mobile", "tablet"):
        context = browser.new_context(**device_config)
    else:
        context = browser.new_context(viewport={"width": viewport_width, "height": viewport_height})
        
    page = context.new_page()
    page.add_init_script("window.addEventListener('contextmenu', e => e.preventDefault(), true);")

    initial_parsed = urlparse(args.url)
    allowed_host = initial_parsed.netloc

    def handle_route(route, request):
        if request.is_navigation_request():
            req_parsed = urlparse(request.url)
            if req_parsed.netloc and req_parsed.netloc != allowed_host:
                print(f"[*] [BLOCKED] Navigation to external URL aborted: {request.url}")
                route.abort()
                return
        route.continue_()

    page.route("**/*", handle_route)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    if args.record:
        wcag_suffix = f"_wcag{args.wcag.replace('.', '_')}" if args.wcag else ""
        sitemap_tag = ""
        if args.sitemap:
            sm_base = os.path.basename(args.sitemap)
            sm_name = os.path.splitext(sm_base)[0]
            sitemap_tag = f"_{sm_name}"
        record_dir = os.path.join("records", f"run{sitemap_tag}{wcag_suffix}_{timestamp}")
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
    
    if args.wcag:
        conformance_level = get_wcag_conformance_level(args.wcag)
        report_file.write(f"# AI Playwright Agent 執行報告 (WCAG {args.wcag} - {conformance_level})\n\n")
    else:
        report_file.write(f"# AI Playwright Agent 執行報告\n\n")
    report_file.write(f"- **時間戳記**: `{timestamp}`\n")
    if args.wcag:
        report_file.write(f"- **WCAG 檢測章節**: `WCAG {args.wcag}` ({conformance_level})\n")
    report_file.write(f"- **任務內容**: {user_task}\n")
    report_file.write(f"- **AI 模型**: `{args.model}`\n")
    report_file.write(f"- **模擬裝置**: `{args.device}`\n")
    report_file.write(f"- **初始網址**: `{args.url}`\n\n")
    report_file.flush()

    total_input_tokens = global_total_input_tokens
    total_output_tokens = global_total_output_tokens
    total_cache_read_tokens = 0
    total_cache_creation_tokens = 0

    try:
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
                unique_links = {}
                for item in site_links:
                    if item["href"] and item["href"].startswith("http"):
                        unique_links[item["href"]] = item["text"] or "無文字說明"
                
                if unique_links:
                    link_items = list(unique_links.items())[:15]
                    links_text = "\n".join([f"- {url} ({text})" for url, text in link_items])
                    extra_instructions += f"\n\n【網站關鍵同源頁面 URL 地圖 (Site Map - Top 15 URLs)】:\n{links_text}\n\n" \
                                          f"**【⚠️ 導航降本增效核心指示】**\n" \
                                          f"1. **禁止自行隨意導航**：系統已為您自動導航至目標頁面。若您因業務邏輯需要巡檢其他子頁面，請優先參考上表 URL 並使用 `navigate` 工具，但請優先完成當前頁面的審查任務。\n" \
                                          f"2. **外部網域已封鎖**：非上表 host 的外部連結已在瀏覽器層面被自動屏蔽，請不要嘗試訪問。"
                    print(f"[✓] 提取完成！已精簡提取頂層 {len(link_items)} 個同源子頁面 URL 注入 AI 上下文。")
            except Exception as e:
                print(f"[WARNING] 提取網站地圖失敗: {e}")

        # 決定目標頁面清單 (Feeder)
        target_pages = []
        sitemap_target_file = args.sitemap if args.sitemap else "sitemaps/sitemap.json"
        
        if args.single_page or (args.url and args.url != INITIAL_URL):
            target_pages = [{"path": urlparse(args.url).path or "/", "url": args.url}]
            print(f"[*] [FEEDER] 執行單一目標網頁: {args.url}")
        elif args.sitemap and os.path.exists(args.sitemap):
            try:
                with open(args.sitemap, "r", encoding="utf-8") as f:
                    sdata = json.load(f)
                    nodes = sdata.get("nodes", {})
                    pending = []
                    for p, n in nodes.items():
                        if not n.get("dynamic_verified_at") and n.get("status") != "CATEGORY":
                            full_url = urllib.parse.urljoin(args.url or INITIAL_URL, p)
                            pending.append({"path": p, "url": full_url})
                    
                    if pending:
                        target_pages = pending
                        print(f"[*] [FEEDER] 從地圖中發現 {len(target_pages)} 個待動態掃描頁面。")
                    else:
                        target_pages = [{"path": "/", "url": args.url or INITIAL_URL}]
                        print(f"[*] [FEEDER] 地圖中無未驗證頁面，預設執行首頁。")
            except Exception as fe:
                print(f"[WARNING] 讀取地圖失敗: {fe}")
                target_pages = [{"path": "/", "url": args.url or INITIAL_URL}]
        else:
            target_pages = [{"path": "/", "url": args.url or INITIAL_URL}]

        for page_idx, target in enumerate(target_pages):
            current_url = target["url"]
            print(f"\n\n{'='*60}")
            print(f"[頁面巡檢] 正在處理第 {page_idx+1}/{len(target_pages)} 頁: {target['path']}")
            print(f"   目標網址: {current_url}")
            print(f"{'='*60}\n")

            if page.url != current_url:
                print(f"[頁面導航] 系統自動跳轉至: {current_url}")
                page.goto(current_url)
                page.wait_for_timeout(1000)
                try:
                    page.focus("body")
                except Exception:
                    pass

            login_user = args.username if args.username is not None else AUTO_LOGIN_USERNAME
            login_pass = args.password if args.password is not None else AUTO_LOGIN_PASSWORD
            
            actual_url = page.url.lower()
            if (login_user or login_pass) and ("login" in actual_url and "login/status" not in actual_url and "login/clienttime" not in actual_url):
                print("[AI 預登入] 檢測到處於登入頁面，執行 AI 自動登入程序...")
                login_toks = perform_ai_login_phase(page, args.model, login_user, login_pass)
                total_input_tokens += login_toks.get("input", 0)
                total_output_tokens += login_toks.get("output", 0)
                total_cache_read_tokens += login_toks.get("cache_read_input_tokens", 0)
                total_cache_creation_tokens += login_toks.get("cache_creation_input_tokens", 0)
                if page_idx > 0 and page.url != current_url:
                    page.goto(current_url)

            initial_screenshot = page.screenshot(type="png")
            
            initial_screenshot_name = f"page_{page_idx}_step_0_initial.png"
            if record_dir:
                with open(os.path.join(record_dir, initial_screenshot_name), "wb") as f:
                    f.write(initial_screenshot)
            report_file.write(f"\n# 頁面巡檢: {target['path']}\n")
            report_file.write(f"## 初始狀態\n")
            report_file.write(f"已導航至 {current_url}，初始畫面如下：\n\n")
            report_file.write(f"![初始截圖]({initial_screenshot_name})\n\n")
            report_file.flush()
            
            page_extra_instructions = extra_instructions
            is_keyboard_task = any(kw in user_task.lower() or kw in page_extra_instructions.lower() for kw in ["keyboard", "tab", "focus", "按鍵", "鍵盤", "焦點"])
            if is_keyboard_task:
                print(f"[*] 執行 [{target['path']}] Focus-Path 掃描...")
                page.wait_for_timeout(1000)
                focus_map = scan_focus_path(page)
                if focus_map:
                    table_lines = ["\n### 本頁面自動化焦點地圖 (Focus Map)\n", "| 順序 | 標籤 | ID | 文字 | 坐標 | 焦點可見 (Focus Visible) |", "| :--- | :--- | :--- | :--- | :--- | :--- |"]
                    for item in focus_map[:35]:
                        vis_status = "YES (Has Outline)" if item.get('focusVis') else f"NO ({item.get('outline', 'none')})"
                        table_lines.append(f"| {item.get('idx',1)} | {item.get('tag','')} | `{item.get('id','')}` | {item.get('text','')} | {item.get('pos',[0,0])} | {vis_status} |")
                    
                    page_extra_instructions += "\n" + "\n".join(table_lines)
                    
                    rigor_mode = args.rigor.lower() if hasattr(args, 'rigor') and args.rigor else "balanced"
                    if rigor_mode == "strict":
                        rigor_guide = (
                            "【嚴謹度策略：精準細緻模式 (Strict Audit)】\n"
                            "• 請採取一步一驗證原則：每個焦點與按鍵請單獨操作並截圖存證，詳實記錄所有可視外框與操作細節供外部審核。"
                        )
                    elif rigor_mode == "fast":
                        rigor_guide = (
                            "【嚴謹度策略：極速低耗模式 (Fast Batch Audit)】\n"
                            "• 請最大化執行效率：積極運用 evaluate_javascript 與多步連續鍵盤動作（例如一次發送多個 Tab）快速走訪焦點鏈。\n"
                            "• 無需每步截圖，僅在發現明確無障礙違規（如焦點遺失、鍵盤陷阱）或任務總結時截圖存證，爭取在 4~8 個回合內高效完成任務。"
                        )
                    else:
                        rigor_guide = (
                            "【嚴謹度策略：均衡推薦模式 (Balanced Audit)】\n"
                            "• 請兼顧深度與效率：充分利用系統已提供的 Focus Map 數據。對於標準且連續的連結/按鈕，可一次發送多個 Tab 或配合 evaluate_javascript 批次確認。\n"
                            "• 當遇到選單展開、彈窗互動、表單操作，或發現潛在違規（如座標異常、隱藏元素聚焦、焦點外框缺失）時，才進行單獨截圖與深度驗證。\n"
                            "• 爭取在 8~14 個回合內完成深度審查並產出總結。"
                        )
                    
                    page_extra_instructions += f"\n\n**【Scoped Audit 指示】**：\n" \
                                              f"1. 你目前被系統主動引導至 `{target['path']}`，請對此頁面進行無障礙驗證。\n" \
                                              f"2. **焦點地圖已提供**：系統已預先為你掃描並附上『Focus Map』數據。請直接利用此數據評估 WCAG 2.1.1 與 2.4.7，**無需**再次執行 `scan_focus_path`。\n" \
                                              f"3. {rigor_guide}\n" \
                                              f"4. **完成任務**：完成此頁面審查後，請產出報告並直接結束對話，以便系統切換至下一頁。"

            active_skill = None
            if args.wcag:
                active_skill = "wcag_audit_sop"
                print(f"[*] 注入專業領域 Skill: {active_skill}")

            interaction = agent.create_initial_interaction(
                user_task, 
                initial_screenshot, 
                page_extra_instructions,
                skill=active_skill
            )
            
            init_tokens = get_interaction_tokens(interaction)
            total_input_tokens += init_tokens["input"]
            total_output_tokens += init_tokens["output"]
            total_cache_read_tokens += init_tokens.get("cache_read_input_tokens", 0)
            total_cache_creation_tokens += init_tokens.get("cache_creation_input_tokens", 0)
            print(f"[*] [PAGE {page_idx+1}] Initial Tokens - In: {init_tokens['input']}, Out: {init_tokens['output']}")
                
            for turn in range(args.max_turns):
                mark_dynamic_verified(sitemap_target_file, page.url)
                
                print(f"\n[PAGE {page_idx+1} | TURN {turn + 1}/{args.max_turns}]")
                
                report_file.write(f"### 第 {turn + 1} 回合\n")
                
                text_response = agent.extract_text_response(interaction)
                if text_response.strip():
                    print(f"[AI 思考輸出]:\n{text_response}\n")
                    report_file.write(f"**AI**: {text_response}\n\n")
                    if not agent.has_function_calls(interaction):
                        if any(kw in text_response for kw in ["WCAG", "合規", "對照表", "診斷報告"]):
                            dump_single_page_settlement_report(sitemap_target_file, page.url, text_response)

                if not agent.has_function_calls(interaction):
                    print(f"[OK] [PAGE {page_idx+1}] 任務完成。")
                    report_file.write(f"**本頁面任務已完成**。\n\n")
                    break
                
                results = execute_function_calls(interaction, page, viewport_width, viewport_height)
                function_responses = get_function_responses(page, results, interaction)
                
                post_screenshot = page.screenshot(type="png")
                screenshot_name = f"page_{page_idx}_turn_{turn + 1}_post.png"
                if record_dir:
                    with open(os.path.join(record_dir, screenshot_name), "wb") as f:
                        f.write(post_screenshot)
                report_file.write(f"![步驟截圖]({screenshot_name})\n\n")
                
                interaction = agent.continue_interaction(interaction.id, function_responses)
                
                turn_tokens = get_interaction_tokens(interaction)
                total_input_tokens += turn_tokens["input"]
                total_output_tokens += turn_tokens["output"]
                total_cache_read_tokens += turn_tokens.get("cache_read_input_tokens", 0)
                total_cache_creation_tokens += turn_tokens.get("cache_creation_input_tokens", 0)
                print(f"[*] [PAGE {page_idx+1} | TURN {turn + 1}] Turn Tokens - In: {turn_tokens['input']}, Out: {turn_tokens['output']}")
            else:
                print(f"[!] [PAGE {page_idx+1}] 已達最大回合數，要求 AI 產出最終總結...")
                report_file.write(f"**已達最大回合數**，產出最終總結... \n\n")
                try:
                    summary_data = agent.get_final_summary(interaction.id)
                    final_summary = summary_data["summary"]
                    total_input_tokens += summary_data["usage"]["input"]
                    total_output_tokens += summary_data["usage"]["output"]
                    
                    report_file.write(f"**AI 最終總結**: \n\n{final_summary}\n\n")
                    dump_single_page_settlement_report(sitemap_target_file, page.url, final_summary)
                    print(f"[OK] [PAGE {page_idx+1}] 最終總結已完成並寫入報告。")
                except Exception as se:
                    print(f"[!] 產出總結失敗: {se}")

        print_token_and_cost_summary(args.model, total_input_tokens, total_output_tokens, report_file, total_cache_read_tokens, total_cache_creation_tokens)
        printed_token_summary = True
        
        print(f"\n[-] 任務結束，將於 {RESULT_OBSERVATION_TIME} 秒後關閉...")
        time.sleep(RESULT_OBSERVATION_TIME)

    except BaseException as e:
        if not isinstance(e, SystemExit) or e.code != 0:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            if 'report_file' in locals() and not report_file.closed:
                report_file.write(f"\n## 執行發生錯誤\n`{str(e)}`\n")

    finally:
        print("\n[~] Cleaning up...")
        if not printed_token_summary:
            try:
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


def run_inspection_task(
    task: str,
    url: str,
    model: str = None,
    wcag: str = None,
    sitemap: str = None,
    device: str = "desktop",
    headless: bool = True,
    record: bool = True,
    role: str = "default",
    behavior: str = "careful",
    output: str = "natural",
    username: str = None,
    password: str = None,
    verify_sitemap: bool = False,
    show_config: bool = False
):
    """
    低耦合的 API 進入點，供編寫測試代碼或 GUI 直接呼叫。
    """
    args = argparse.Namespace()
    args.task = task
    args.url = url
    args.model = model or MODEL_NAME
    args.wcag = wcag
    args.sitemap = sitemap
    args.device = device
    args.headless = headless
    args.record = record
    args.role = role
    args.behavior = behavior
    args.output = output
    args.username = username
    args.password = password
    args.verify_sitemap = verify_sitemap
    args.show_config = show_config
    args.content = None
    
    return run_agent_workflow(args)


def main():
    args = parse_arguments()
    run_agent_workflow(args)


if __name__ == "__main__":
    main()
