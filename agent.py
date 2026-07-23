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
import time
import urllib.parse
from urllib.parse import urlparse, urljoin
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
        print(f"[AI LOGIN] Initial Tokens - In: {init_tokens['input']}, Out: {init_tokens['output']}")
        
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
            print(f"[AI LOGIN] [回合 {turn + 1}] Turn Tokens - In: {turn_tokens['input']}, Out: {turn_tokens['output']}")
            
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


def verify_and_sync_sitemap(page, base_url: str, sitemap_path: str, max_pages: int = None, model_name: str = None, username: str = None, password: str = None) -> dict:
    """
    動態走訪、校對並同步更新 Sitemap JSON 檔案（支援中斷續傳 checkpointing）。
    - 支援舊格式 (陣列) 與新格式 (字典 nodes)。
    - 校對 200/404 狀態、<title>。
    - 自動掃描同源連結，發現新頁面動態掛載至 children 並新增 node。
    - 支援 max_pages (回合上限) 分批中斷與寫回 checkpoint，優先續接未驗證頁面。
    - 若地圖不存在，自動創建最小地圖（只包含根路徑）。
    - 覆蓋寫回 sitemap_path JSON。
    - model_name, username, password: 用於會話超時時自動重新登入。
    """
    import urllib.parse
    print(f"[*] 啟動地圖動態走訪校對與更新引擎 (Sitemap Sync Engine)...")
    print(f"  - 目標基礎網址: {base_url}")
    print(f"  - 目標地圖檔案: {sitemap_path}")
    if max_pages:
        print(f"  - 本次設定走訪上限: {max_pages} 頁 (避免超過回合數/Token庫存)")
    
    # 若地圖不存在，自動創建最小地圖
    if not os.path.exists(sitemap_path):
        print(f"[🌱] 地圖檔案不存在，自動創建最小地圖...")
        
        # 確保目錄存在
        sitemap_dir = os.path.dirname(sitemap_path)
        if sitemap_dir and not os.path.exists(sitemap_dir):
            os.makedirs(sitemap_dir, exist_ok=True)
        
        # 創建最小地圖：只包含根路徑
        parsed_url = urllib.parse.urlparse(base_url)
        minimal_sitemap = {
            "base_path": "/",
            "total_pages": 1,
            "target_url": base_url,
            # "scan_languages": ["de"],  # 可選：限制掃描的語言版本，null 或不設置表示掃描所有語言
            "nodes": {
                "/": {
                    "path": "/",
                    "title": "未校對頁面",
                    "parent": None,
                    "children": [],
                    "is_leaf": True,
                    "depth": 0,
                    "status": "UNVERIFIED"
                }
            }
        }
        
        try:
            with open(sitemap_path, "w", encoding="utf-8") as sf:
                json.dump(minimal_sitemap, sf, ensure_ascii=False, indent=2)
            print(f"[✅] 最小地圖已創建：{sitemap_path}")
            print(f"  - 將從根路徑 '/' 開始自動探索整個網站結構")
        except Exception as e:
            print(f"[ERROR] 創建最小地圖失敗: {e}")
            return {"success": False, "error": str(e)}
        
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
    
    # 提取語言過濾配置（如果存在）
    scan_languages = sitemap_data.get("scan_languages", None)  # None = 掃描所有語言
    if scan_languages:
        print(f"[📌] 語言過濾已啟用：只掃描 {scan_languages} 語言版本")
    
    # 從 sitemap metadata 讀取認證資訊（如果未提供）
    if not username:
        username = sitemap_data.get("default_username", "")
    if not password:
        password = sitemap_data.get("default_password", "")

    # 優先排序佇列：未驗證存在 (initialized 為空/False) 排最前，已驗證存在排最後
    # 特別處理：根節點 "/" 永遠排在最前面，以確保能第一時間掃描到所有頂層導航連結
    
    # 清理地圖中的靜態資源節點（圖片、CSS、JS 等）
    static_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', 
                        '.css', '.js', '.woff', '.woff2', '.ttf', '.eot', 
                        '.pdf', '.zip', '.mp4', '.mp3', '.wav')
    removed_static_resources = []
    for path in list(nodes.keys()):
        if path.lower().endswith(static_extensions):
            # 從父節點的 children 中移除
            parent_path = nodes[path].get("parent")
            if parent_path and parent_path in nodes:
                if path in nodes[parent_path].get("children", []):
                    nodes[parent_path]["children"].remove(path)
            # 從 nodes 中刪除
            del nodes[path]
            removed_static_resources.append(path)
    
    if removed_static_resources:
        print(f"[🧹] 清理了 {len(removed_static_resources)} 個靜態資源節點 (圖片、CSS、JS 等)")
    
    # 清理後重新獲取節點列表
    unverified_paths = [p for p, n in nodes.items() if not n.get("initialized")]
    verified_paths = [p for p, n in nodes.items() if n.get("initialized")]
    
    # 將根節點和主要頁面優先排序（確保能快速掃描到新連結）
    priority_paths = ["/", "/login", "/overview", "/advanced"]
    priority_queue = [p for p in priority_paths if p in verified_paths]
    other_verified = [p for p in verified_paths if p not in priority_paths]

    if verified_paths and unverified_paths:
        print(f"[*] [SITEMAP RESUME] 檢測到中斷點：已驗證 {len(verified_paths)} 頁，將優先續接剩餘未驗證的 {len(unverified_paths)} 頁！")
        queue = unverified_paths + priority_queue + other_verified
    elif unverified_paths:
        queue = unverified_paths
    else:
        # 全部都驗證過，若繼續執行則進行重新輪詢校對，優先掃描主要導航頁面
        print(f"[*] [SITEMAP FULL RE-VERIFY] 全站所有 {len(nodes)} 頁先前皆已校對完成，開始新一輪複查...")
        print(f"  💡 優先掃描根節點與主要導航頁面以發現新連結")
        queue = priority_queue + other_verified

    visited = set()
    discovered_count = 0
    dead_count = 0
    updated_titles = 0
    visited_in_run = 0
    dead_link_patterns = set()  # 記錄已知的死鏈模式（如：以 ../manual/ 開頭的路徑）
    
    # 计算实际总数用于进度显示
    total_to_scan = len(queue)
    
    # 预估扫描时间（每页约 1.5 秒）
    estimated_time_seconds = total_to_scan * 1.5
    estimated_minutes = int(estimated_time_seconds / 60)
    print(f"[⏱️] 預計掃描時間: 約 {estimated_minutes} 分鐘 ({total_to_scan} 頁 × 1.5 秒/頁)")
    print(f"[💡] 提示: 掃描過程中會即時檢測登入狀態，自動重新登入")

    while queue:
        if max_pages and visited_in_run >= max_pages:
            remaining_unverified = len([p for p, n in nodes.items() if not n.get("initialized") and p not in visited])
            print(f"[⏸️] 已達到本次設定的最高走訪回合數 ({max_pages} 頁)。")
            print(f"  - 本次進度已實時寫入 JSON 檔中斷點 (Checkpoint)。")
            print(f"  - 下次再執行此地圖更新時，將自動跳過已驗證頁面，繼續校對剩餘 {remaining_unverified} 頁！")
            break

        rel_path = queue.pop(0)
        if rel_path not in nodes:
            continue
        if rel_path in visited:
            continue
            
        # 檢查是否匹配已知的死鏈模式
        is_known_dead_pattern = False
        for pattern in dead_link_patterns:
            if rel_path.startswith(pattern):
                is_known_dead_pattern = True
                # 直接刪除該節點，不浪費時間訪問
                if rel_path in nodes:
                    parent_path = nodes[rel_path].get("parent")
                    if parent_path and parent_path in nodes:
                        if rel_path in nodes[parent_path].get("children", []):
                            nodes[parent_path]["children"].remove(rel_path)
                    del nodes[rel_path]
                break
        
        if is_known_dead_pattern:
            continue
        visited.add(rel_path)
        visited_in_run += 1

        full_url = urllib.parse.urljoin(base_url, rel_path)
        
        # 顯示進度百分比
        progress_pct = int((visited_in_run / total_to_scan) * 100) if total_to_scan > 0 else 0
        print(f"[*] [SITEMAP VERIFY] [{visited_in_run}/{total_to_scan}] ({progress_pct}%) 正在走訪頁面: {rel_path} -> {full_url}")

        try:
            response = page.goto(full_url, timeout=12000, wait_until="domcontentloaded")
            # 額外等待 1 秒以確保 React SPA 完成客戶端渲染與所有連結載入 (加速掃描)
            page.wait_for_timeout(1000)
            
            # ⚡ 立即檢測 URL 跳轉（提早發現登出問題）
            actual_url = page.url.lower()
            expected_url = full_url.lower()
            
            # 檢查是否被跳轉到登入頁（會話超時的最早信號）
            if actual_url != expected_url and "login" in actual_url and "login/status" not in actual_url and "login/clienttime" not in actual_url:
                print(f"[⚠️] 檢測到頁面跳轉至登入頁 ({rel_path} → {page.url})")
                print(f"[⚠️] 會話已失效，正在重新登入...")
                
                # 嘗試重新登入
                if model_name and username and password:
                    try:
                        from core.login_engine import perform_ai_login_phase
                        login_result = perform_ai_login_phase(
                            page=page,
                            model_name=model_name,
                            username=username,
                            password=password
                        )
                        
                        if login_result.get("success"):
                            print(f"[✓] 重新登入成功！重新訪問目標頁面: {rel_path}")
                            # 重新訪問原始目標頁面
                            response = page.goto(full_url, timeout=12000, wait_until="domcontentloaded")
                            page.wait_for_timeout(1000)
                        else:
                            print(f"[✗] 重新登入失敗！停止掃描以避免產生虛假死鏈。")
                            break
                    except Exception as e:
                        print(f"[✗] 重新登入錯誤: {e}。停止掃描。")
                        break
                else:
                    print(f"[✗] 缺少認證資訊 (model/username/password)，無法自動重新登入。停止掃描。")
                    break
            
            # 滾動頁面以觸發懶加載內容和隱藏的連結
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(300)
                page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass
            
            status_code = response.status if response else 200

            # 檢查前端 Client-side SPA 404 (例如 React Router 渲染的 404，雖然 HTTP 返回 200)
            is_client_side_404 = False
            if status_code < 400 and response:
                try:
                    title_lower = (page.title() or "").lower()
                    if "404" in title_lower or "not found" in title_lower:
                        is_client_side_404 = True
                    else:
                        is_client_side_404 = page.evaluate("""
                            (() => {
                                const txt = document.body.innerText.toLowerCase();
                                const has404 = txt.includes("404");
                                const hasNotFound = txt.includes("not found") || 
                                                    txt.includes("notfound") || 
                                                    txt.includes("找不到") || 
                                                    txt.includes("不存在") || 
                                                    txt.includes("無此") ||
                                                    txt.includes("error");
                                return has404 && hasNotFound;
                            })()
                        """)
                except Exception:
                    pass

            if status_code >= 400 or not response or is_client_side_404:
                has_children = len(nodes[rel_path].get("children", [])) > 0
                if has_children:
                    # 情況 A：它是某個分頁的父節點（目錄節點）但本身不存在。
                    # 我們保留它以維持樹狀階層結構，標記其為「導覽型目錄」，不作為死鏈報錯。
                    print(f"  📁 檢測到目錄節點為導覽目錄 (HTTP {status_code}{'，前端 404' if is_client_side_404 else ''})。標記為導覽目錄。")
                    nodes[rel_path]["status"] = "CATEGORY"
                    nodes[rel_path]["error"] = False
                    nodes[rel_path]["initialized"] = True
                    nodes[rel_path]["initialized_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    # 注意：CATEGORY 節點不計入 dead_count，因為它們是正常的導覽結構，非實際錯誤
                    continue
                else:
                    # 情況 B：它是不具子節點的實體葉頁面（死鏈）。
                    # 我們將其自地圖中徹底移除並執行自癒。
                    print(f"  ⚠️ 檢測到實體死鏈 (HTTP {status_code}{'，前端 404' if is_client_side_404 else ''})。自地圖中移除並自癒結構...")
                    
                    # 記錄死鏈模式（如果是以 ../ 開頭的相對路徑）
                    if rel_path.startswith("../"):
                        # 提取前綴作為模式（例如 ../manual/ 或 ../login/）
                        parts = rel_path.split("/")
                        if len(parts) >= 3:
                            pattern = "/".join(parts[:3]) + "/"  # 例如 ../manual/
                            dead_link_patterns.add(pattern)
                            print(f"  📝 記錄死鏈模式: {pattern} (後續將自動跳過相似路徑)")
                    
                    # 自其父節點 of children 陣列中移除
                    parent_path = nodes[rel_path].get("parent")
                    if parent_path in nodes:
                        if rel_path in nodes[parent_path].get("children", []):
                            try:
                                nodes[parent_path]["children"].remove(rel_path)
                            except Exception:
                                pass
                                
                    # 亦自其所有子節點重設其 parent 屬性，並移交給該節點的父節點 (繼承關係)
                    for child_path in nodes[rel_path].get("children", []):
                        if child_path in nodes:
                            nodes[child_path]["parent"] = parent_path
                            if parent_path in nodes:
                                if "children" not in nodes[parent_path]:
                                    nodes[parent_path]["children"] = []
                                if child_path not in nodes[parent_path]["children"]:
                                    nodes[parent_path]["children"].append(child_path)
                                    
                    # 從節點字典中刪除該節點
                    del nodes[rel_path]
                    dead_count += 1
                    continue
            else:
                current_title = page.title() or nodes[rel_path].get("title", "")
                if current_title and nodes[rel_path].get("title") != current_title:
                    nodes[rel_path]["title"] = current_title
                    updated_titles += 1

                nodes[rel_path]["status"] = "OK"
                nodes[rel_path]["error"] = False
                nodes[rel_path]["initialized"] = True

                # 提取同源連結（增強版：支援 React Router Link 和動態渲染）
                extract_links_script = r"""
                (() => {
                    // 等待可能的動態渲染完成
                    const links = new Set();
                    
                    // 方法 1: 標準 <a> 標籤
                    document.querySelectorAll('a[href]').forEach(a => {
                        links.add(a.href);  // 使用 .href 獲取絕對 URL
                    });
                    
                    // 方法 2: React Router Link 組件可能渲染的任何帶有 href 的元素
                    document.querySelectorAll('[href]').forEach(el => {
                        // 使用 .href 獲取絕對 URL（如果存在），否則手動轉換相對路徑
                        let absoluteUrl;
                        if (el.href) {
                            // 如果元素有 .href 屬性（<a>, <area>, <link> 等），直接使用
                            absoluteUrl = el.href;
                        } else {
                            // 否則手動將相對路徑轉換為絕對路徑
                            try {
                                const relativeUrl = el.getAttribute('href');
                                absoluteUrl = new URL(relativeUrl, window.location.href).href;
                            } catch(e) {
                                return;  // 無效的 URL，跳過
                            }
                        }
                        links.add(absoluteUrl);
                    });
                    
                    // 方法 3: 檢查所有按鈕和可點擊元素的 onClick 事件（可能包含路由跳轉）
                    document.querySelectorAll('button, [role="button"], [onclick]').forEach(el => {
                        const onclick = el.getAttribute('onclick') || el.textContent;
                        if (onclick) {
                            // 嘗試從 onClick 中提取路由路徑
                            const pathMatch = onclick.match(/['"]\/[^'"]*['"]/) || 
                                            onclick.match(/navigate.*?['"]\/[^'"]*['"]/) ||
                                            onclick.match(/to:\s*['"]\/[^'"]*['"]/)
                            if (pathMatch && pathMatch[0]) {
                                const path = pathMatch[0].replace(/['"]/g, '');
                                links.add(window.location.origin + path);
                            }
                        }
                    });
                    
                    // 過濾同源連結
                    return Array.from(links).filter(href => {
                        if (!href || href === 'null') return false;
                        try {
                            const u = new URL(href, window.location.href);
                            return u.host === window.location.host;
                        } catch(e) { 
                            return false; 
                        }
                    });
                })()
                """
                try:
                    discovered_hrefs = page.evaluate(extract_links_script)
                    if discovered_hrefs:
                        print(f"  🔍 在當前頁面發現 {len(discovered_hrefs)} 個同源連結")
                except Exception as e:
                    print(f"  ⚠️ 提取連結失敗: {e}")
                    discovered_hrefs = []

                if "children" not in nodes[rel_path]:
                    nodes[rel_path]["children"] = []

                for href in discovered_hrefs:
                    pu = urllib.parse.urlparse(href)
                    child_rel = pu.path if pu.path else "/"
                    if pu.query:
                        child_rel += "?" + pu.query

                    # 跳過無效路徑、靜態資源文件（圖片、CSS、JS 等）
                    static_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', 
                                       '.css', '.js', '.woff', '.woff2', '.ttf', '.eot', 
                                       '.pdf', '.zip', '.mp4', '.mp3', '.wav')
                    
                    # 跳過 JSON API 端點（包括帶查詢參數的）
                    # 例如：/data/PhoneBook.json?search=A
                    is_json_endpoint = '.json' in child_rel.lower().split('?')[0]
                    
                    # 額外過濾：跳過明顯錯誤的相對路徑（不是以 /html/ 開頭且不是根路徑）
                    # 例如：overview/index.html, phone/phone_internet.html 等
                    # 這些是由於 HTML 中的相對路徑被錯誤解析導致的
                    is_invalid_relative = (
                        child_rel != "/" and 
                        not child_rel.startswith("/html/") and 
                        not child_rel.startswith("/data/") and
                        "/" in child_rel and
                        not child_rel.startswith("http")
                    )
                    
                    # 語言過濾（基於 sitemap 配置）
                    is_unwanted_lang = False
                    if scan_languages:  # 如果配置了語言過濾
                        if '?lang=' in child_rel or '&lang=' in child_rel:
                            # 提取當前鏈接的語言參數
                            import re
                            lang_match = re.search(r'[?&]lang=([a-z]{2})', child_rel)
                            if lang_match:
                                current_lang = lang_match.group(1)
                                if current_lang not in scan_languages:
                                    is_unwanted_lang = True
                    
                    if (child_rel == rel_path or 
                        child_rel.startswith("javascript:") or 
                        child_rel.startswith("#") or 
                        child_rel.lower().endswith(static_extensions) or
                        is_json_endpoint or
                        is_invalid_relative or
                        is_unwanted_lang):
                        continue

                    if child_rel not in nodes[rel_path]["children"]:
                        nodes[rel_path]["children"].append(child_rel)

                    # 如果節點完全不存在，創建新節點
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
                        print(f"  ✨ 發現新頁面節點: {child_rel} (父節點: {rel_path})")
                    
                    # 將未走訪過且不在隊列中的節點加入隊列（包括重新發現的未初始化節點）
                    if child_rel not in visited and child_rel not in queue:
                        queue.append(child_rel)

            # 記錄通過時間戳記 (Checkpointing)
            nodes[rel_path]["initialized_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        except Exception as err:
            print(f"  ⚠️ 走訪頁面失敗 {rel_path}: {err}")
            nodes[rel_path]["status"] = "ERROR"
            nodes[rel_path]["error"] = str(err)
            nodes[rel_path]["initialized_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
        if dead_link_patterns:
            print(f"  - 識別死鏈模式: {len(dead_link_patterns)} 個 (已自動跳過相似路徑)")
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
    if args.task:
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
            login_user = args.username if args.username is not None else AUTO_LOGIN_USERNAME
            login_pass = args.password if args.password is not None else AUTO_LOGIN_PASSWORD
            if login_user or login_pass:
                login_toks = perform_ai_login_phase(page, args.model, login_user, login_pass)
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
                # 走訪初始化任務完全程式化不消耗 token，不受 args.max_turns 限制，設定 max_pages 為 None (無上限)
                # 傳入認證資訊以支援自動重新登入
                verify_and_sync_sitemap(
                    page=page, 
                    base_url=target_url, 
                    sitemap_path=sitemap_target, 
                    max_pages=None,
                    model_name=args.model,
                    username=login_user,
                    password=login_pass
                )
                return

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
                                          f"1. **禁止自行隨意導航**：系統已為您自動導航至目標頁面。若您因業務邏輯需要巡檢其他子頁面，請優先參考上表 URL 並使用 `navigate` 工具，但請優先完成當前頁面的審查任務。\n" \
                                          f"2. **外部網域已封鎖**：非上表 host 的外部連結已在瀏覽器層面被自動屏蔽，請不要嘗試訪問。"
                    print(f"[✓] 提取完成！已精簡提取頂層 {len(link_items)} 個同源子頁面 URL 注入 AI 上下文 (省 80% Token)。")
            except Exception as e:
                print(f"[WARNING] 提取網站地圖失敗: {e}")

        # --- 餵食者 (Feeder) 邏輯：決定目標頁面清單 ---
        target_pages = []
        sitemap_target_file = args.sitemap if args.sitemap else "sitemaps/sitemap.json"
        
        # 情境 A: 使用者明確指定了單一網頁，或啟用了單網頁強制模式
        if args.single_page or (args.url and args.url != INITIAL_URL):
            target_pages = [{"path": urlparse(args.url).path or "/", "url": args.url}]
            print(f"[*] [FEEDER] 執行單一目標網頁: {args.url}")
        
        # 情境 B: 使用者指定了 Sitemap 且沒有指定特定 URL，則掃描地圖中未驗證的頁面
        elif args.sitemap and os.path.exists(args.sitemap):
            try:
                with open(args.sitemap, "r", encoding="utf-8") as f:
                    sdata = json.load(f)
                    nodes = sdata.get("nodes", {})
                    # 篩選出未動態驗證過且不是目錄的頁面
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
        
        # 情境 C: 預設執行單一初始網址
        else:
            target_pages = [{"path": "/", "url": args.url or INITIAL_URL}]

        # --- 餵食者循環 (Feeder Loop) ---
        for page_idx, target in enumerate(target_pages):
            current_url = target["url"]
            print(f"\n\n{'#'*80}")
            print(f"🚀 [FEEDER] 正在處理第 {page_idx+1}/{len(target_pages)} 頁: {target['path']}")
            print(f"   目標網址: {current_url}")
            print(f"{'#'*80}\n")

            # 系統自動導航至目標頁面 (減少 AI 導航損耗)
            if page.url != current_url:
                print(f"[>>] 系統自動跳轉至: {current_url}")
                page.goto(current_url)
                page.wait_for_timeout(1000)
                try:
                    page.focus("body")
                except Exception:
                    pass

            # 若為跨頁掃描，重新執行登入檢查（避免 session 過期）
            if page_idx > 0:
                from config import AUTO_LOGIN_USERNAME, AUTO_LOGIN_PASSWORD
                login_user = args.username if args.username is not None else AUTO_LOGIN_USERNAME
                login_pass = args.password if args.password is not None else AUTO_LOGIN_PASSWORD
                
                # 簡單檢查是否被踢回登入頁
                actual_url = page.url.lower()
                if "login" in actual_url and "login/status" not in actual_url:
                    print("[!] 檢測到 Session 失效，執行自動重新登入...")
                    login_toks = perform_ai_login_phase(page, args.model, login_user, login_pass)
                    total_input_tokens += login_toks["input"]
                    total_output_tokens += login_toks["output"]
                    page.goto(current_url) # 重新回到目標頁

            initial_screenshot = page.screenshot(type="png")
            
            # 儲存初始截圖
            initial_screenshot_name = f"page_{page_idx}_step_0_initial.png"
            if record_dir:
                with open(os.path.join(record_dir, initial_screenshot_name), "wb") as f:
                    f.write(initial_screenshot)
            report_file.write(f"\n# 🌐 頁面巡檢: {target['path']}\n")
            report_file.write(f"## 🎬 初始狀態\n")
            report_file.write(f"已導航至 {current_url}，初始畫面如下：\n\n")
            report_file.write(f"![初始截圖]({initial_screenshot_name})\n\n")
            report_file.flush()
            
            # 取得該頁面的 Focus Map
            page_extra_instructions = extra_instructions
            is_keyboard_task = any(kw in user_task.lower() or kw in page_extra_instructions.lower() for kw in ["keyboard", "tab", "focus", "按鍵", "鍵盤", "焦點"])
            if is_keyboard_task:
                print(f"[*] 執行 [{target['path']}] Focus-Path 掃描...")
                page.wait_for_timeout(1000)
                focus_map = scan_focus_path(page)
                if focus_map:
                    table_lines = ["\n### 🔍 本頁面自動化焦點地圖 (Focus Map)\n", "| 順序 | 標籤 | ID | 文字 | 坐標 | 焦點可見 (Focus Visible) |", "| :--- | :--- | :--- | :--- | :--- | :--- |"]
                    for item in focus_map[:35]: # 限制數量避免 token 太長
                        vis_status = "✅ YES (Has Outline)" if item.get('focusVis') else f"❌ NO ({item.get('outline', 'none')})"
                        table_lines.append(f"| {item.get('idx',1)} | {item.get('tag','')} | `{item.get('id','')}` | {item.get('text','')} | {item.get('pos',[0,0])} | {vis_status} |")
                    
                    page_extra_instructions += "\n" + "\n".join(table_lines)
                    page_extra_instructions += f"\n\n**【⚠️ Scoped Audit 指示】**：\n" \
                                              f"1. 你目前被系統主動引導至 `{target['path']}`，請對此頁面進行無障礙驗證。\n" \
                                              f"2. **焦點地圖已提供**：系統已預先為你掃描並附上『Focus Map』數據（包含坐標與 Outline 樣式）。請直接利用此數據評估 WCAG 2.1.1 (鍵盤) 與 2.4.7 (焦點可見度)，**無需**再次執行 `scan_focus_path` 或手動逐一按 Tab 鍵驗證（除非你需要確認動態變化）。\n" \
                                              f"3. **完成任務**：完成此頁面審查後，請產出報告並直接結束對話，以便系統切換至下一頁。"

            # 決定是否需要注入特定領域的專業技能 (Skill / SOP)
            active_skill = None
            if args.wcag:
                active_skill = "wcag_audit_sop"
                print(f"[*] 注入專業領域 Skill: {active_skill}")

            # 建立該頁面的專屬互動 (這會清除之前的對話 Log / Reset Context)
            interaction = agent.create_initial_interaction(
                user_task, 
                initial_screenshot, 
                page_extra_instructions,
                skill=active_skill
            )
            
            # 紀錄 Token 消耗
            init_tokens = get_interaction_tokens(interaction)
            total_input_tokens += init_tokens["input"]
            total_output_tokens += init_tokens["output"]
            print(f"[*] [PAGE {page_idx+1}] Initial Tokens - In: {init_tokens['input']}, Out: {init_tokens['output']}")
                
            # AI 單頁代理執行循環
            for turn in range(args.max_turns):
                # 自動標記當前頁面 URL 為已動態 AI 校對 Checkpoint
                mark_dynamic_verified(sitemap_target_file, page.url)
                
                print(f"\n[PAGE {page_idx+1} | TURN {turn + 1}/{args.max_turns}]")
                
                report_file.write(f"### 🔄 第 {turn + 1} 回合\n")
                
                text_response = agent.extract_text_response(interaction)
                if text_response.strip():
                    print(f"🤖 [AI 思考輸出]:\n{text_response}\n")
                    report_file.write(f"🤖 **AI**: {text_response}\n\n")
                    # 只有當 AI 本回合 **沒有** 呼叫工具時（代表是最終結論或階段性總結），才寫入結案報告
                    if not agent.has_function_calls(interaction):
                        if any(kw in text_response for kw in ["WCAG", "合規", "對照表", "診斷報告"]):
                            dump_single_page_settlement_report(sitemap_target_file, page.url, text_response)

                if not agent.has_function_calls(interaction):
                    print(f"[✓] [PAGE {page_idx+1}] 任務完成。")
                    report_file.write(f"✅ **本頁面任務已完成**。\n\n")
                    break
                
                results = execute_function_calls(interaction, page, viewport_width, viewport_height)
                function_responses = get_function_responses(page, results, interaction)
                
                # 拍照
                post_screenshot = page.screenshot(type="png")
                screenshot_name = f"page_{page_idx}_turn_{turn + 1}_post.png"
                if record_dir:
                    with open(os.path.join(record_dir, screenshot_name), "wb") as f:
                        f.write(post_screenshot)
                report_file.write(f"📸 ![步驟截圖]({screenshot_name})\n\n")
                
                interaction = agent.continue_interaction(interaction.id, function_responses)
                
                turn_tokens = get_interaction_tokens(interaction)
                total_input_tokens += turn_tokens["input"]
                total_output_tokens += turn_tokens["output"]
                print(f"[*] [PAGE {page_idx+1} | TURN {turn + 1}] Turn Tokens - In: {turn_tokens['input']}, Out: {turn_tokens['output']}")
            else:
                print(f"[!] [PAGE {page_idx+1}] 已達最大回合數，要求 AI 產出最終總結...")
                report_file.write(f"⚠️ **已達最大回合數**，產出最終總結... \n\n")
                try:
                    summary_data = agent.get_final_summary(interaction.id)
                    final_summary = summary_data["summary"]
                    total_input_tokens += summary_data["usage"]["input"]
                    total_output_tokens += summary_data["usage"]["output"]
                    
                    report_file.write(f"🤖 **AI 最終總結**: \n\n{final_summary}\n\n")
                    # 將最大回合數強迫產出的總結也寫入 Sitemap settlement
                    dump_single_page_settlement_report(sitemap_target_file, page.url, final_summary)
                    print(f"[✓] [PAGE {page_idx+1}] 最終總結已完成並寫入報告。")
                except Exception as se:
                    print(f"[!] 產出總結失敗: {se}")

        # --- 結算所有頁面的 Token ---
        print_token_and_cost_summary(args.model, total_input_tokens, total_output_tokens, report_file)
        printed_token_summary = True
        
        print(f"\n[-] 任務結束，將於 {RESULT_OBSERVATION_TIME} 秒後關閉...")
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
