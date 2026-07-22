"""
Gemini + Playwright 自動化代理程式
使用 Google Gemini 的 Computer Use API 來自動操作瀏覽器

使用方法：
  基本：python agent.py "你的任務"
  進階：python agent.py -m gemini-2.0-flash-exp -r tester "任務"
  幫助：python agent.py --help
"""

import sys
import config
from reporting.single_page_report import (
    get_map_records_dir,
    get_page_report_relpath,
    dump_single_page_settlement_report
)
from core.sitemap_engine import (
    mark_dynamic_verified,
    build_wcag_coverage_table
)
from core.login_engine import perform_ai_login_phase
from core.static_audit import (
    perform_local_site_audit,
    check_task_suitability_for_axe,
    is_wcag_guideline_static,
    get_violation_wcag_level,
    get_wcag_conformance_level
)
from core.prompt_builder import print_token_and_cost_summary, build_wcag_prompt
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
                       
    parser.add_argument('--verify-sitemap', action='store_true', default=False,
                       help='啟動地圖動態走訪校對與更新引擎，校對標題、狀態碼並動態寫回 JSON 地圖檔案。')
    
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


def get_map_records_dir(sitemap_name: str) -> tuple:
    """傳回以 Map 命名的獨立報告目錄 (records/<map_stem>/)"""
    map_stem = os.path.splitext(os.path.basename(sitemap_name))[0]
    map_dir = os.path.join("records", map_stem)
    os.makedirs(map_dir, exist_ok=True)
    return map_dir, map_dir


def get_page_report_relpath(sitemap_name: str, rel_path: str) -> str:
    """計算單頁報告相對檔案路徑 (完全依照 Sitemap URL 目錄階層做資料夾分類)"""
    map_stem = os.path.splitext(os.path.basename(sitemap_name))[0]
    clean_path = rel_path.strip("/")
    if not clean_path:
        file_dir = os.path.join("records", map_stem)
        file_name = "index.md"
    else:
        parts = clean_path.split("/")
        if len(parts) == 1:
            file_dir = os.path.join("records", map_stem)
            file_name = f"{parts[0].replace('.', '_')}.md"
        else:
            file_dir = os.path.join("records", map_stem, *parts[:-1])
            file_name = f"{parts[-1].replace('.', '_')}.md"
            
    os.makedirs(file_dir, exist_ok=True)
    return os.path.join(file_dir, file_name)


def mark_dynamic_verified(sitemap_path: str, page_url: str):
    """
    將目標網址在 sitemap.json 中對應的頁面節點標記為已動態 AI 校對 (dynamic_verified_at)，並關聯單頁報告檔案路徑
    """
    if not sitemap_path or not page_url:
        return
        
    actual_path = sitemap_path
    if not os.path.exists(actual_path):
        alt_path = os.path.join("sitemaps", os.path.basename(sitemap_path))
        if os.path.exists(alt_path):
            actual_path = alt_path
        else:
            return
            
    try:
        from urllib.parse import urlparse
        parsed = urlparse(page_url)
        rel_path = parsed.path or "/"
        
        with open(actual_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        nodes = data.get("nodes", {})
        target_key = None
        for key in nodes:
            if key == rel_path or key.rstrip("/") == rel_path.rstrip("/") or (key.endswith("/index.html") and key.replace("/index.html", "") == rel_path.rstrip("/")):
                target_key = key
                break
                
        if target_key and target_key in nodes:
            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            report_relpath = get_page_report_relpath(actual_path, target_key)
            
            # 確保單頁報告目錄存在
            map_dir, pages_dir = get_map_records_dir(actual_path)
            report_full_path = os.path.join(os.getcwd(), report_relpath)
            
            # 若單頁報告尚未建立，建立基本無障礙結算檔案
            if not os.path.exists(report_full_path):
                with open(report_full_path, "w", encoding="utf-8") as pf:
                    pf.write(f"# 📝 頁面無障礙巡檢報告 (Page Audit Report)\n\n")
                    pf.write(f"- **頁面路徑**: `{target_key}`\n")
                    pf.write(f"- **完整網址**: {page_url}\n")
                    pf.write(f"- **校對類型**: 🤖 動態 AI 巡檢 (Dynamic AI Audit)\n")
                    pf.write(f"- **校對時間**: `{now_str}`\n\n")
                    pf.write(f"## 📊 檢測結論與記錄\n此頁面已完成動態 AI 鍵盤與視覺焦點無障礙走訪驗證。\n")

            nodes[target_key]["dynamic_verified_at"] = now_str
            nodes[target_key]["report_file"] = report_relpath
            with open(actual_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print(f"[MAP SYNC] 🤖 成功寫入動態校對 Checkpoint: [{target_key}] ({now_str})")
    except Exception as e:
        pass


def dump_single_page_settlement_report(sitemap_path: str, page_url: str, content_text: str, audit_type: str = "dynamic"):
    """
    將單頁的靜態 Axe-core 審查結果與動態 AI WCAG 報告完全整合寫入 records/<map_stem>/pages/<clean_name>.md 單頁結算文檔中
    """
    if not sitemap_path or not page_url or not content_text or len(content_text.strip()) < 20:
        return
        
    actual_path = sitemap_path
    if not os.path.exists(actual_path):
        alt_path = os.path.join("sitemaps", os.path.basename(sitemap_path))
        if os.path.exists(alt_path):
            actual_path = alt_path
        else:
            return
            
    try:
        from urllib.parse import urlparse
        parsed = urlparse(page_url)
        rel_path = parsed.path or "/"
        
        target_key = rel_path
        map_dir, pages_dir = get_map_records_dir(actual_path)
        report_relpath = get_page_report_relpath(actual_path, target_key)
        report_full_path = os.path.join(os.getcwd(), report_relpath)
        
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 若單頁報告檔案已存在（例如先跑了靜態，再跑動態），進行合一追加整合
        existing_static_content = ""
        if os.path.exists(report_full_path):
            try:
                with open(report_full_path, "r", encoding="utf-8") as ef:
                    old_text = ef.read()
                    if "## ⚡ 第一部分：靜態代碼無障礙審查" in old_text and audit_type == "dynamic":
                        parts = old_text.split("## 🤖 第二部分：動態 AI")
                        existing_static_content = parts[0]
            except Exception:
                pass

        if audit_type == "static":
            header_type_str = "⚡ 本地靜態代碼巡檢 (Static Audit)"
            section_block = f"## ⚡ 第一部分：靜態代碼無障礙審查結果 (Static Axe-core Audit)\n- **校對時間**: `{now_str}`\n\n{content_text}\n"
        elif audit_type == "dynamic":
            header_type_str = "🤖 動態 AI 鍵盤與視覺巡檢 (Dynamic AI Audit)"
            section_block = f"## 🤖 第二部分：動態 AI 鍵盤與視覺對照審查結果 (Dynamic AI Audit)\n- **校對時間**: `{now_str}`\n\n{content_text}\n"
        else:
            header_type_str = "雙模合一巡檢 (Hybrid Audit)"
            section_block = content_text

        if existing_static_content and audit_type == "dynamic":
            full_md_content = existing_static_content.strip() + "\n\n---------------------------------------------------\n\n" + section_block
        else:
            full_md_content = f"# 📝 頁面無障礙綜合巡檢報告 (Unified Page Accessibility Report)\n\n" \
                              f"- **頁面相對路徑**: `{target_key}`\n" \
                              f"- **完整網址**: {page_url}\n" \
                              f"- **最新更新時間**: `{now_str}`\n" \
                              f"- **巡檢類型**: {header_type_str}\n\n" \
                              f"---------------------------------------------------\n\n" \
                              f"{section_block}"
        
        with open(report_full_path, "w", encoding="utf-8") as pf:
            pf.write(full_md_content)
            
        with open(actual_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        nodes = data.get("nodes", {})
        target_key_matched = None
        for key in nodes:
            if key == rel_path or key.rstrip("/") == rel_path.rstrip("/") or (key.endswith("/index.html") and key.replace("/index.html", "") == rel_path.rstrip("/")):
                target_key_matched = key
                break
                
        if target_key_matched and target_key_matched in nodes:
            if audit_type == "static":
                nodes[target_key_matched]["verified_at"] = now_str
            else:
                nodes[target_key_matched]["dynamic_verified_at"] = now_str
            nodes[target_key_matched]["report_file"] = report_relpath
            with open(actual_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
                
        print(f"[PAGE SETTLEMENT] 📄 成功寫入單頁合一報告 ({audit_type}): {report_relpath}")
    except Exception as e:
        print(f"[WARNING] Dump 單頁報告失敗: {e}")


def is_wcag_guideline_static(wcag_ver: str) -> bool:
    """
    判斷特定的 WCAG 指南是否主要是靜態代碼審查（可以完全由 Axe-core / 本地腳本覆蓋）
    """
    static_guidelines = ["all", "1.1", "1.2", "1.3", "1.4", "3.1", "3.2", "3.3", "4.1"]
    for sg in static_guidelines:
        if wcag_ver.lower().startswith(sg):
            return True
    return False


def get_violation_wcag_level(tags: list) -> str:
    """
    從 Axe-core violation 的 tags 中，提取出 WCAG 等級 (A, AA, AAA)
    """
    for tag in tags:
        if tag.startswith("wcag") or "wcag" in tag:
            if tag.endswith("aaa"):
                return "AAA"
            elif tag.endswith("aa"):
                return "AA"
            elif tag.endswith("a"):
                return "A"
    return "N/A"


def get_wcag_conformance_level(wcag_ver: str) -> str:
    """
    根據 WCAG 章節，回傳其所屬的等級範圍 (Level A/AA/AAA)
    """
    levels = {
        "1.1": "Level A",
        "1.2": "Level A / AA / AAA",
        "1.3": "Level A / AA / AAA",
        "1.4": "Level A / AA / AAA",
        "2.1": "Level A / AAA",
        "2.2": "Level A / AAA",
        "2.3": "Level A / AAA",
        "2.4": "Level A / AA / AAA",
        "2.5": "Level A / AA / AAA",
        "3.1": "Level A / AA / AAA",
        "3.2": "Level A / AA / AAA",
        "3.3": "Level A / AA / AAA",
        "4.1": "Level A / AA"
    }
    return levels.get(wcag_ver, "N/A")


def build_wcag_coverage_table(wcag_ver: str) -> list:
    """
    產出無障礙條款對應的 Success Criteria 3 位數細分表格與合規等級 (Level A/AA/AAA)
    """
    lines = []
    w_upper = wcag_ver.upper() if wcag_ver else ""
    
    if w_upper in ["ALL", "STATIC_ALL"]:
        lines.append("### 📋 靜態全量無障礙檢測涵蓋條款與規範細分 (Static ALL Coverage)")
        lines.append("| 條款編號 | 成功條款名稱 (Success Criteria) | 合規等級 | 檢測方式與說明 |")
        lines.append("| :--- | :--- | :---: | :--- |")
        lines.append("| **WCAG 1.1.1** | 非文字內容 (Non-text Content) | Level A | ⚡ 靜態 DOM / img alt / svg aria-label 檢查 |")
        lines.append("| **WCAG 1.3.1** | 資訊與關係 (Info and Relationships) | Level A | ⚡ 靜態 h1-h6 階層 / form label / table header 檢查 |")
        lines.append("| **WCAG 1.3.5** | 識別輸入用途 (Identify Input Purpose) | Level AA | ⚡ 靜態 input autocomplete 屬性驗證 |")
        lines.append("| **WCAG 1.4.1** | 色彩的使用 (Use of Color) | Level A | ⚡ 靜態文字與背景純顏色依賴檢查 |")
        lines.append("| **WCAG 1.4.3** | 對比度 (最小門檻 4.5:1 / 3:1) | Level AA | ⚡ 靜態計算文字與背景色調對比度 |")
        lines.append("| **WCAG 1.4.11**| 非文字對比度 (Non-text Contrast 3:1) | Level AA | ⚡ 靜態 UI 組件與邊框對比度計算 |")
        lines.append("| **WCAG 2.4.1** | 旁路區塊 (Bypass Blocks / Skip Link) | Level A | ⚡ 靜態導航區域 Skip-to-content 錨點驗證 |")
        lines.append("| **WCAG 2.4.2** | 頁面標題 (Page Titled) | Level A | ⚡ 靜態 `<title>` 標籤存在性與非空驗證 |")
        lines.append("| **WCAG 3.1.1** | 網頁語言 (Language of Page) | Level A | ⚡ 靜態 `<html lang>` 屬性合法性驗證 |")
        lines.append("| **WCAG 4.1.2** | 名稱、角色與數值 (Name, Role, Value) | Level A | ⚡ 靜態 ARIA Role 與 Button 命名合法性 |")
        lines.append("")
    elif w_upper in ["DYNAMIC_ALL"]:
        lines.append("### 📋 動態全量無障礙檢測涵蓋條款與規範細分 (Dynamic ALL Coverage)")
        lines.append("| 條款編號 | 成功條款名稱 (Success Criteria) | 合規等級 | 檢測方式與說明 |")
        lines.append("| :--- | :--- | :---: | :--- |")
        lines.append("| **WCAG 2.1.1** | 鍵盤操作 (Keyboard Accessible) | Level A | 🤖 Focus-Scan + AI 鍵盤按鍵連鎖比對 |")
        lines.append("| **WCAG 2.1.2** | 無鍵盤陷阱 (No Keyboard Trap) | Level A | 🤖 AI 焦點循環陷阱與 Escape 脫離測試 |")
        lines.append("| **WCAG 2.1.4** | 單鍵快捷鍵 (Character Key Shortcuts) | Level A | 🤖 AI 快捷鍵觸發與閉鎖行為防護驗證 |")
        lines.append("| **WCAG 2.2.1** | 可調整時間 (Timing Adjustable) | Level A | 🤖 AI 超時防護與 Session 警示判定 |")
        lines.append("| **WCAG 2.4.7** | 焦點可見 (Focus Visible Outline) | Level AA | 🤖 Focus-Scan 焦點環外框樣式算繪分析 |")
        lines.append("| **WCAG 2.5.3** | 標籤中的名稱 (Label in Name) | Level A | 🤖 AI 視覺文字與可存取名稱 (Accessible Name) 一致性 |")
        lines.append("")
    else:
        lines.append(f"### 📋 專項無障礙條款檢測範圍 (`WCAG {wcag_ver}` Coverage)")
        lines.append("| 條款編號 | 成功條款名稱 (Success Criteria) | 合規等級 | 說明 |")
        lines.append("| :--- | :--- | :---: | :--- |")
        clean = wcag_ver.replace(".", "")
        if clean.startswith("11"):
            lines.append("| **WCAG 1.1.1** | 非文字內容 (Non-text Content) | Level A | 檢查圖片與多媒體之替代文字 (alt) |")
        elif clean.startswith("13"):
            lines.append("| **WCAG 1.3.1** | 資訊與關係 (Info and Relationships) | Level A | 檢查語意標籤與標題階層結構 |")
            lines.append("| **WCAG 1.3.5** | 識別輸入用途 (Identify Input Purpose) | Level AA | 檢查表單自動填寫屬性 |")
        elif clean.startswith("14"):
            lines.append("| **WCAG 1.4.1** | 色彩的使用 (Use of Color) | Level A | 檢查視覺傳達色彩依賴 |")
            lines.append("| **WCAG 1.4.3** | 文字色彩對比度 (Contrast Minimum) | Level AA | 檢查文字前景與背景 4.5:1 對比度 |")
            lines.append("| **WCAG 1.4.11**| 非文字對比度 (Non-text Contrast) | Level AA | 檢查UI介面組件 3:1 對比度 |")
        elif clean.startswith("21"):
            lines.append("| **WCAG 2.1.1** | 鍵盤 (Keyboard) | Level A | 驗證全站功能皆可用 Tab/方向鍵操作 |")
            lines.append("| **WCAG 2.1.2** | 無鍵盤陷阱 (No Keyboard Trap) | Level A | 驗證焦點不會卡死在 Modal 或彈窗中 |")
            lines.append("| **WCAG 2.1.4** | 單字元快捷鍵 (Character Key Shortcuts) | Level A | 驗證非修飾鍵快捷鍵可關閉或重置 |")
        elif clean.startswith("24"):
            lines.append("| **WCAG 2.4.1** | 跳過區塊 (Bypass Blocks) | Level A | 檢查是否有快速跳轉至主內容區連結 |")
            lines.append("| **WCAG 2.4.2** | 頁面標題 (Page Titled) | Level A | 檢查 `<title>` 標籤內容與網頁主題相關性 |")
            lines.append("| **WCAG 2.4.7** | 焦點可見 (Focus Visible) | Level AA | 檢查鍵盤聚焦時是否有清晰外框 |")
        elif clean.startswith("31"):
            lines.append("| **WCAG 3.1.1** | 網頁語言 (Language of Page) | Level A | 檢查 `<html lang>` 屬性 |")
        elif clean.startswith("41"):
            lines.append("| **WCAG 4.1.2** | 名稱、角色與數值 (Name, Role, Value) | Level A | 檢查 DOM 元素與 ARIA 屬性合法性 |")
        else:
            lines.append(f"| **WCAG {wcag_ver}** | 專項條款檢測 | Level A/AA | 針對 WCAG {wcag_ver} 條款進行深層驗證 |")
        lines.append("")
        
    return lines


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
        f"請登入此網站（備用帳號為 '{username}'，密碼為 '{password}'）。\n"
        "1. 首先判斷當前畫面是否為登入頁面。如果已經在登入狀態（或非登入頁面），請立刻使用文字說明並結束任務。\n"
        "2. 【⚠️ 單一密碼欄位與雙欄位判定關鍵原則】：\n"
        f"   - **單一欄位頁面**：若頁面只有一個輸入框（例如路由器、網管裝置僅有一個密碼輸入框），請『直接在該唯一輸入框點擊並輸入密碼 \"{password}\"』，不要嘗試尋找帳號欄位或輸入帳號！\n"
        f"   - **雙欄位頁面**：若頁面同時包含帳號與密碼兩個輸入框，才分別點擊並輸入帳號 \"{username}\" 與密碼 \"{password}\"。\n"
        "3. 為了避免現代前端框架（如 React/Vue）的狀態綁定 (state binding) 失效，請『務必使用滑鼠點擊輸入框』並『使用鍵盤打字 (type/key)』，『絕對不要』使用 Javascript (evaluate_javascript) 直接修改欄位的 value。\n"
        "4. 點擊登入/送出按鈕 (Submit/Login/OK)，並等待登入跳轉完成。\n"
        "5. 登入成功進入後台儀表板或首頁後，請立刻結束任務（不要進行任何無障礙檢測，直接完成任務）。"
    )
    
    viewport_width = 1024 if is_claude else 1440
    viewport_height = 768 if is_claude else 900
    
    try:
        login_input_tokens = 0
        login_output_tokens = 0
        login_total_tokens = 0
        
        # DOM 探測：檢測頁面上可見輸入框數量 (分辨單欄位路由器登入頁 vs 雙欄位登入頁)
        single_field_hint = ""
        try:
            input_detect_script = """
            (() => {
                const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="checkbox"]):not([type="radio"])'))
                    .filter(i => i.offsetWidth > 0 && i.offsetHeight > 0);
                return {
                    count: inputs.length,
                    types: inputs.map(i => i.type || 'text'),
                    ids: inputs.map(i => i.id || i.name || '')
                };
            })()
            """
            det_res = page.evaluate(input_detect_script)
            if det_res and det_res.get("count") == 1:
                print(f"[AI LOGIN] [DOM 偵測] 發現當前頁面為「單一欄位」登入頁！將指示 AI 直接填入密碼 '{password}'。")
                single_field_hint = f"\n\n**【💡 系統 DOM 偵測提醒】**：當前頁面只有 1 個可見輸入框！這是一個單一欄位登入頁，請直接點擊該欄位並輸入密碼 '{password}' 進行登入，切勿輸入帳號名稱。"
        except Exception:
            pass

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
                idx = item.get("idx", item.get("index", 1))
                tag = item.get("tag", item.get("tagName", "element"))
                table_lines.append(f"| {idx} | {tag} | `{item.get('id', '')}` | {item.get('text', '')} |")
            focus_map_text = "\n".join(table_lines)
            
        extra_instructions = f"\n\n{focus_map_text}{single_field_hint}\n\n請以最快、最有效率的步驟完成登入，一旦登入完成看到主頁/後台，請不要做任何其他操作，直接停止呼叫工具以結束任務。"
        
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
            print("[AI LOGIN] [WARNING] 🔴 認證失敗：密碼輸入欄位依然存在！登入未能成功切換頁面。")
            return {
                "input": login_input_tokens,
                "output": login_output_tokens,
                "total": login_total_tokens,
                "success": False
            }
        else:
            print("[AI LOGIN] [✓] 登入驗證成功！密碼欄位已消失，瀏覽器已成功切換至登入後頁面。")
            
        print("[AI LOGIN] [✓] 預登入程序結束，回傳控制權給掃描器。\n")
        return {
            "input": login_input_tokens,
            "output": login_output_tokens,
            "total": login_total_tokens,
            "success": True
        }
    except Exception as e:
        print(f"[AI LOGIN] [WARNING] AI 預登入出錯: {e}")
        return {
            "input": 0,
            "output": 0,
            "total": 0,
            "success": False
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


def verify_and_sync_sitemap(page, base_url: str, sitemap_path: str, max_pages: int = None) -> dict:
    """
    動態走訪、校對並同步更新 Sitemap JSON 檔案（支援中斷續傳 checkpointing）。
    - 支援舊格式 (陣列) 與新格式 (字典 nodes)。
    - 校對 200/404 狀態、<title>。
    - 自動掃描同源連結，發現新頁面動態掛載至 children 並新增 node。
    - 支援 max_pages (回合上限) 分批中斷與寫回 checkpoint，優先續接未驗證頁面。
    - 覆蓋寫回 sitemap_path JSON。
    """
    import urllib.parse
    print(f"[*] 啟動地圖動態走訪校對與更新引擎 (Sitemap Sync Engine)...")
    print(f"  - 目標基礎網址: {base_url}")
    print(f"  - 目標地圖檔案: {sitemap_path}")
    if max_pages:
        print(f"  - 本次設定走訪上限: {max_pages} 頁 (避免超過回合數/Token庫存)")
    
    if not os.path.exists(sitemap_path):
        print(f"[ERROR] 找不到地圖檔案: {sitemap_path}")
        return {"success": False, "error": "File not found"}
        
    try:
        with open(sitemap_path, "r", encoding="utf-8") as sf:
            raw_data = json.load(sf)
    except Exception as e:
        print(f"[ERROR] 讀取地圖檔案失敗: {e}")
        return {"success": False, "error": str(e)}

    nodes = {}
    base_path = "/"
    
    if isinstance(raw_data, list):
        base_path = "/"
        for item in raw_data:
            url_str = item if isinstance(item, str) else item.get("url", "")
            if not url_str:
                continue
            parsed = urllib.parse.urlparse(url_str)
            rel_path = parsed.path if parsed.path else "/"
            if parsed.query:
                rel_path += "?" + parsed.query
                
            nodes[rel_path] = {
                "path": rel_path,
                "title": "未校對頁面",
                "parent": None,
                "children": [],
                "is_leaf": True,
                "depth": rel_path.strip("/").count("/") + 1 if rel_path != "/" else 0
            }
        sitemap_data = {
            "base_path": base_path,
            "total_pages": len(nodes),
            "nodes": nodes
        }
    elif isinstance(raw_data, dict):
        sitemap_data = raw_data
        base_path = sitemap_data.get("base_path", "/")
        nodes = sitemap_data.get("nodes", {})
    else:
        print(f"[ERROR] 未知的地圖格式: {type(raw_data)}")
        return {"success": False, "error": "Invalid format"}

    # 優先排序佇列：未校對 (verified_at 為空) 排最前，已校對過排最後
    unverified_paths = [p for p, n in nodes.items() if not n.get("verified_at")]
    verified_paths = [p for p, n in nodes.items() if n.get("verified_at")]

    if verified_paths and unverified_paths:
        print(f"[*] [SITEMAP RESUME] 檢測到中斷點：已驗證 {len(verified_paths)} 頁，將優先續接剩餘未驗證的 {len(unverified_paths)} 頁！")
        queue = unverified_paths + verified_paths
    elif unverified_paths:
        queue = unverified_paths
    else:
        # 全部都驗證過，若繼續執行則進行重新輪詢校對
        print(f"[*] [SITEMAP FULL RE-VERIFY] 全站所有 {len(nodes)} 頁先前皆已校對完成，開始新一輪複查...")
        queue = list(nodes.keys())

    visited = set()
    discovered_count = 0
    dead_count = 0
    updated_titles = 0
    visited_in_run = 0

    while queue:
        if max_pages and visited_in_run >= max_pages:
            remaining_unverified = len([p for p, n in nodes.items() if not n.get("verified_at") and p not in visited])
            print(f"[⏸️] 已達到本次設定的最高走訪回合數 ({max_pages} 頁)。")
            print(f"  - 本次進度已實時寫入 JSON 檔中斷點 (Checkpoint)。")
            print(f"  - 下次再執行此地圖更新時，將自動跳過已驗證頁面，繼續校對剩餘 {remaining_unverified} 頁！")
            break

        rel_path = queue.pop(0)
        if rel_path in visited:
            continue
        visited.add(rel_path)
        visited_in_run += 1

        full_url = urllib.parse.urljoin(base_url, rel_path)
        print(f"[*] [SITEMAP VERIFY] [{visited_in_run}/{max_pages if max_pages else len(nodes)}] 正在走訪頁面: {rel_path} -> {full_url}")

        try:
            response = page.goto(full_url, timeout=12000, wait_until="domcontentloaded")
            status_code = response.status if response else 200

            if status_code >= 400 or not response:
                print(f"  ⚠️ 死鏈/狀態異常 HTTP {status_code}")
                nodes[rel_path]["status"] = f"HTTP_{status_code}"
                nodes[rel_path]["error"] = True
                dead_count += 1
            else:
                current_title = page.title() or nodes[rel_path].get("title", "")
                if current_title and nodes[rel_path].get("title") != current_title:
                    nodes[rel_path]["title"] = current_title
                    updated_titles += 1

                nodes[rel_path]["status"] = "OK"
                nodes[rel_path]["error"] = False

                # 提取同源連結
                extract_links_script = """
                (() => {
                    return Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href)
                        .filter(href => {
                            try {
                                const u = new URL(href);
                                return u.host === window.location.host;
                            } catch(e) { return false; }
                        });
                })()
                """
                try:
                    discovered_hrefs = page.evaluate(extract_links_script)
                except Exception:
                    discovered_hrefs = []

                if "children" not in nodes[rel_path]:
                    nodes[rel_path]["children"] = []

                for href in discovered_hrefs:
                    pu = urllib.parse.urlparse(href)
                    child_rel = pu.path if pu.path else "/"
                    if pu.query:
                        child_rel += "?" + pu.query

                    if child_rel == rel_path or child_rel.startswith("javascript:") or child_rel.startswith("#"):
                        continue

                    if child_rel not in nodes[rel_path]["children"]:
                        nodes[rel_path]["children"].append(child_rel)

                    if child_rel not in nodes:
                        depth = child_rel.strip("/").count("/") + 1 if child_rel != "/" else 0
                        nodes[child_rel] = {
                            "path": child_rel,
                            "title": f"新發現頁面 ({child_rel})",
                            "parent": rel_path,
                            "children": [],
                            "is_leaf": True,
                            "depth": depth,
                            "status": "UNVERIFIED"
                        }
                        discovered_count += 1
                        if child_rel not in visited and child_rel not in queue:
                            queue.append(child_rel)

            # 記錄通過時間戳記 (Checkpointing)
            nodes[rel_path]["verified_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        except Exception as err:
            print(f"  ⚠️ 走訪頁面失敗 {rel_path}: {err}")
            nodes[rel_path]["status"] = "ERROR"
            nodes[rel_path]["error"] = str(err)
            nodes[rel_path]["verified_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            dead_count += 1

        # 每走訪 5 個頁面實時寫入一次檔案防崩潰
        if visited_in_run % 5 == 0:
            try:
                sitemap_data["nodes"] = nodes
                sitemap_data["total_pages"] = len(nodes)
                sitemap_data["last_verified"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(sitemap_path, "w", encoding="utf-8") as sf:
                    json.dump(sitemap_data, sf, ensure_ascii=False, indent=2)
            except Exception:
                pass

    # 重新計算與更新 is_leaf
    for p, node in nodes.items():
        node["is_leaf"] = (len(node.get("children", [])) == 0)

    sitemap_data["total_pages"] = len(nodes)
    sitemap_data["last_verified"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sitemap_data["nodes"] = nodes

    # 回寫檔案
    try:
        with open(sitemap_path, "w", encoding="utf-8") as sf:
            json.dump(sitemap_data, sf, ensure_ascii=False, indent=2)
        print("=" * 60)
        print(f"[✓] 地圖動態走訪與校對完成！")
        print(f"  - 走訪校對總頁數: {len(visited)}")
        print(f"  - 動態新發現頁面: {discovered_count}")
        print(f"  - 標題更正次數: {updated_titles}")
        print(f"  - 死鏈/異常數: {dead_count}")
        print(f"  - 最新頁面總數: {len(nodes)}")
        print(f"[✓] 已成功同步並覆蓋更新地圖檔: '{sitemap_path}'")
        print("=" * 60)
    except Exception as save_err:
        print(f"[ERROR] 儲存更新地圖失敗: {save_err}")

    return {
        "success": True,
        "visited_count": len(visited),
        "discovered_count": discovered_count,
        "updated_titles": updated_titles,
        "dead_count": dead_count,
        "total_nodes": len(nodes)
    }








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
                if login_toks.get("success") is False:
                    print("\n[AI LOGIN] ❌ AI 預先登入失敗！認證未通過，終止後續巡檢任務。\n")
                    if args.record and record_dir:
                        report_path = os.path.join(record_dir, "report.md")
                        with open(report_path, "w", encoding="utf-8") as rf:
                            rf.write("# ❌ 任務失敗與終止報告\n\nAI 預先登入認證失敗，無法獲取進入後台授權，任務已自動提前終止。\n")
                    return
            
            # 執行地圖動態校對與更新引擎 (若開啟 --verify-sitemap)
            if args.verify_sitemap:
                sitemap_target = args.sitemap if args.sitemap else os.path.join("sitemaps", "sitemap.json")
                max_p = args.max_turns if args.max_turns else None
                verify_and_sync_sitemap(page, target_url, sitemap_target, max_pages=max_p)

            # 建立報告內容與檔名
            report_lines = []
            raw_results = {}
            
            if args.wcag:
                # 執行本地全站自動巡檢
                audit_res = perform_local_site_audit(page, target_url, args.wcag, sitemap_path=args.sitemap)
                total_violations = audit_res["total_violations"]
                
                print(f"[✓] 本地全站巡檢完成！共發現 {total_violations} 個無障礙違規項目。")
                print("="*60)
                
                conformance_level = get_wcag_conformance_level(args.wcag)
                report_lines.append(f"# 📝 WCAG {args.wcag} 本地自動化無障礙全站巡檢報告\n")
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
                
                report_lines.append("### 📊 違規等級統計 (Violations by Level)")
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
                            
                            # 獲取並顯示 WCAG 等級
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
                except Exception as diag_err:
                    pass
                print(f"    - 頁面標題: '{title}'")
                print(f"    - HTML 大小: {html_len} bytes, DOM 元素數: {elements_count}")
                
                axe_results = run_axe_audit(page)
                violations = axe_results.get("violations", [])
                
                print(f"[✓] 本地代碼檢測完成！共發現 {len(violations)} 個無障礙違規項目。")
                print("="*60)
                
                # 統計違規等級
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
                        
                        # 獲取並顯示 WCAG 等級
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
            has_key = CLAUDE_API_KEY if is_claude else GEMINI_API_KEY
            
            if has_key:
                print("\n[AI] 正在將本地檢測結果遞交給 AI 進行智慧診斷與評估...")
                try:
                    # 整理傳遞給 AI 的檢測結果摘要 (先行附帶 WCAG 3位數對照表)
                    summary_for_ai = []
                    summary_for_ai.append("【WCAG 2.2 官方涵蓋條款與 3 位數 Success Criteria 對照基準】:")
                    summary_for_ai.extend(build_wcag_coverage_table(args.wcag))
                    summary_for_ai.append("\n【實測 Axe-core 違規數據】:")
                    
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
            if login_toks.get("success") is False:
                print("\n[AI LOGIN] ❌ AI 預先登入失敗！認證未通過，終止後續動態任務。\n")
                if record_dir:
                    report_path = os.path.join(record_dir, "report.md")
                    with open(report_path, "w", encoding="utf-8") as rf:
                        rf.write("# ❌ 任務失敗與終止報告\n\nAI 預先登入認證失敗，無法獲取進入後台授權，任務已自動提前終止。\n")
                return

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
                            rf.write(f"- **WCAG 檢測章節**: `WCAG 1.2`\n")
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
                    idx = item.get("idx", item.get("index", 1))
                    tag = item.get("tag", item.get("tagName", "element"))
                    el_id = item.get("id", "")
                    className = item.get("className", "")
                    text = item.get("text", "")
                    pos = item.get("pos", [item.get("x", 0), item.get("y", 0)])
                    x, y = pos[0], pos[1]
                    outline = item.get("outline", "visible" if item.get("focusVis") else "none")
                    
                    table_lines.append(
                        f"| {idx} | {tag} | `{el_id}` | `{className}` | {text} | {x},{y} | `{outline}` |"
                    )
                
                max_t_str = f"{args.max_turns} 回合" if args.max_turns else "10~25 回合"
                focus_map_text = "\n".join(table_lines)
                extra_instructions += f"\n\n{focus_map_text}\n\n**【⚠️ 核心操作指示：請嚴格遵守以節省 Token 且確保無障礙檢測準確性】**\n" \
                                      f"1. **對照視覺與地圖 (關鍵)**：上表為本地能被 focus() 的元素。請仔細觀察螢幕截圖中的所有「視覺上可互動元素」（例如選單、按鈕、以及特別注意分頁標籤如 **IPv4/IPv6**、**2.4GHz/5GHz** 等）。如果截圖中看得見某個互動元素，但它**不在**上表的 Focus Map 中，代表該元素「完全無法被鍵盤聚焦」，這是嚴重的 **WCAG 2.1.1 (Keyboard) 違規**！請直接在結論中指出此違規，並說明哪些元素缺失。\n" \
                                      f"2. **禁止無意義遍歷**：你**絕對不需要**手動按 Tab 鍵逐一走過上表每一個正常的元素！請直接利用 Focus Map 進行靜態對照與分析。\n" \
                                      f"3. **針對疑點標靶測試**：你**只需要針對有疑慮的 1~2 個特定元素**（例如有視覺標籤但地圖中缺失的元素，或是地圖中顯示 `outline: none` 的元素）進行鍵盤按鍵或點擊實體切換，以驗證其是否可以被 Enter (Return) 鍵激活，或確認是否真的無法聚焦。\n" \
                                      f"4. **多鍵發送捷徑**：如果你需要按多次 Tab 鍵來到達某個元素，你可以將按鍵以空格分隔在同一個指令中發送（例如：`\"text\": \"Tab Tab Tab Tab\"`），系統會在一回合內連續按鍵，請多加利用以節省回合數。\n" \
                                      f"5. **高效率完成任務**：驗證完重點頁面與疑點後，**請立即產出『包含 3 位數 WCAG 合規表格』的最終診斷報告並結束任務**。請將整個任務控制在 **{max_t_str}** 內完成。**"
                
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
                    link_items = list(unique_links.items())[:15]
                    links_text = "\n".join([f"- {url} ({text})" for url, text in link_items])
                    extra_instructions += f"\n\n【網站關鍵同源頁面 URL 地圖 (Site Map - Top 15 URLs)】:\n{links_text}\n\n" \
                                          f"**【⚠️ 導航降本增效核心指示】**\n" \
                                          f"1. **直接 URL 導航**：上表列出了網站的核心內部頁面 URL。如果你需要巡檢或跳轉至其他子頁面，**請直接使用 `navigate` 工具載入對應網址**，絕對不要手動去點擊選單按鈕！這可以為您節省高達 90% 的時間與 Token 消耗。\n" \
                                          f"2. **外部網域已封鎖**：非上表 host 的外部連結已在瀏覽器層面被自動屏蔽，請不要嘗試訪問。"
                    print(f"[✓] 提取完成！已精簡提取頂層 {len(link_items)} 個同源子頁面 URL 注入 AI 上下文 (省 80% Token)。")
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
            # 自動標記當前頁面 URL 為已動態 AI 校對 Checkpoint
            sitemap_target_file = args.sitemap if args.sitemap else "smart4-map.json"
            mark_dynamic_verified(sitemap_target_file, page.url)
            
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
                
                # 若 AI 文字回應包含 WCAG 合規對照表或詳細診斷報告，將其完全 Dump 至單頁結算檔案中
                if any(kw in text_response for kw in ["WCAG", "合規", "對照表", "條款", "第 1 章", "診斷報告", "Success Criteria"]):
                    dump_single_page_settlement_report(sitemap_target_file, page.url, text_response)

            # 檢查是否有操作指令，若無則結束
            if not agent.has_function_calls(interaction):
                print("\n[OK] Task completed")
                report_file.write(f"✅ **任務已完成**：AI 未發送進一步的操作指令。\n\n")
                log_file.write("Task completed.\n")
                if text_response.strip():
                    dump_single_page_settlement_report(sitemap_target_file, page.url, text_response)
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
            
            # 擷取執行後狀態並同步地圖 Checkpoint
            function_responses = get_function_responses(page, results, interaction)
            mark_dynamic_verified(sitemap_target_file, page.url)
            
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
            try:
                sum_res = agent.get_final_summary(interaction.id)
                summary = ""
                if isinstance(sum_res, dict):
                    summary = sum_res.get("summary", "")
                    usage = sum_res.get("usage", {})
                    total_input_tokens += usage.get("input", 0)
                    total_output_tokens += usage.get("output", 0)
                    total_tokens += usage.get("total", 0)
                elif isinstance(sum_res, str):
                    summary = sum_res

                if summary and summary.strip():
                    print(f"\n[AI 最終總結結論]\n{summary}\n")
                    report_file.write(f"🤖 **AI 最終評估總結結論**:\n{summary}\n\n")
                    log_file.write(f"AI Final Summary: {summary}\n")
                    dump_single_page_settlement_report(sitemap_target_file, page.url, summary)
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
