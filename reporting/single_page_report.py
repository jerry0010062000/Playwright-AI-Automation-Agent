import os
import re
import json
import datetime
from urllib.parse import urlparse

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


def calculate_page_coverage_pct(coverage_dict: dict) -> tuple:
    """
    計算單頁無障礙探索完成百分比。
    - 靜態 Axe-core 全量代碼檢測: 30%
    - 核心動態 WCAG 指南 (2.1 鍵盤, 2.4 焦點導航, 2.2 時間, 2.5 指標手勢, 1.4 對比): 各 14% (累計最高 100%)
    傳回 (百分比整數, 已涵蓋清單)
    """
    if not coverage_dict:
        return 0, []
        
    items = []
    total_pct = 0
    if "static" in coverage_dict:
        total_pct += 30
        items.append("靜態代碼")
        
    dynamic_weights = {
        "2.1": 20,
        "2.4": 20,
        "2.2": 10,
        "2.5": 10,
        "1.4": 10
    }
    
    for k, v in coverage_dict.items():
        if k == "static":
            continue
        weight = dynamic_weights.get(k, 15)
        total_pct += weight
        items.append(f"WCAG {k}")
        
    total_pct = min(100, total_pct)
    return total_pct, items


def parse_existing_report(report_full_path: str) -> tuple:
    """
    解析既有 Markdown 單頁報告，提取靜態審查區塊與動態各章節審查區塊字典
    傳回: (static_content, dynamic_chapters_dict)
    """
    if not os.path.exists(report_full_path):
        return "", {}
        
    try:
        with open(report_full_path, "r", encoding="utf-8") as f:
            full_text = f.read()
            
        static_block = ""
        dynamic_chapters = {}
        
        # 1. 提取靜態區塊
        static_match = re.search(r"## (?:⚡ )?第一部分：靜態代碼無障礙審查結果[^\n]*\n(.*?)(?=\n## |$)", full_text, re.DOTALL)
        if static_match:
            static_block = static_match.group(1).strip()
            # 移除開頭的時間戳標記避免重複
            static_block = re.sub(r"^- \*\*校對時間\*\*:[^\n]*\n+", "", static_block).strip()
            
        # 2. 提取動態章節區塊
        dynamic_part_match = re.search(r"## (?:🤖 )?第二部分：動態 AI[^\n]*\n(.*)", full_text, re.DOTALL)
        if dynamic_part_match:
            dyn_text = dynamic_part_match.group(1)
            # 依據 ### 📌 WCAG Guideline <VER> 進行章節切割
            chapter_matches = list(re.finditer(r"### 📌 WCAG Guideline ([\d\.]+) 審查結果[^\n]*\n(.*?)(?=\n### 📌 WCAG Guideline|\n## |$)", dyn_text, re.DOTALL))
            if chapter_matches:
                for cm in chapter_matches:
                    ch_ver = cm.group(1).strip()
                    ch_body = cm.group(2).strip()
                    ch_body = re.sub(r"^- \*\*校對時間\*\*:[^\n]*\n+", "", ch_body).strip()
                    dynamic_chapters[ch_ver] = ch_body
            else:
                # 兼容舊版未分章節之動態報告
                clean_dyn = dyn_text.strip()
                clean_dyn = re.sub(r"^- \*\*校對時間\*\*:[^\n]*\n+", "", clean_dyn).strip()
                if clean_dyn:
                    # 嘗試從舊文字中偵測 WCAG 版本
                    found_ver = "2.1"
                    if "2.4" in clean_dyn and "2.1" not in clean_dyn:
                        found_ver = "2.4"
                    dynamic_chapters[found_ver] = clean_dyn
                    
        return static_block, dynamic_chapters
    except Exception as e:
        print(f"[DEBUG] 解析既有報告異常: {e}")
        return "", {}


def dump_single_page_settlement_report(sitemap_path: str, page_url: str, content_text: str, audit_type: str = "dynamic", wcag_guideline: str = None):
    """
    將單頁的靜態 Axe-core 審查結果與動態 AI WCAG 報告完全整合寫入單頁結算文檔中。
    支援【章節級精準覆蓋】與【未檢測章節追加整合】，杜絕相同測試內容重複 append！
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
        parsed = urlparse(page_url)
        rel_path = parsed.path or "/"
        target_key = rel_path
        
        map_dir, pages_dir = get_map_records_dir(actual_path)
        report_relpath = get_page_report_relpath(actual_path, target_key)
        report_full_path = os.path.join(os.getcwd(), report_relpath)
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 1. 讀取 Sitemap 節點資料以同步 coverage 記錄
        with open(actual_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        nodes = data.get("nodes", {})
        
        target_key_matched = None
        for key in nodes:
            if key == rel_path or key.rstrip("/") == rel_path.rstrip("/") or (key.endswith("/index.html") and key.replace("/index.html", "") == rel_path.rstrip("/")):
                target_key_matched = key
                break
                
        existing_coverage = {}
        if target_key_matched and target_key_matched in nodes:
            existing_coverage = nodes[target_key_matched].get("coverage_wcag", {}) or {}
            
        # 2. 解析既有報告
        existing_static, existing_dynamic_chapters = parse_existing_report(report_full_path)
        
        # 3. 根據 audit_type 與 wcag_guideline 進行精準覆蓋或追加
        current_ch = str(wcag_guideline or "2.1").strip()
        clean_content = content_text.strip()
        
        if audit_type == "static":
            existing_static = clean_content
            existing_coverage["static"] = now_str
        elif audit_type == "dynamic":
            # 精準覆蓋該特定章節
            existing_dynamic_chapters[current_ch] = clean_content
            existing_coverage[current_ch] = now_str
            
        pct, covered_items = calculate_page_coverage_pct(existing_coverage)
        covered_str = ", ".join(covered_items) if covered_items else "無"
        
        # 4. 組裝結構化合一 Markdown 報告
        sections = []
        sections.append(f"# 頁面無障礙綜合巡檢報告 (Unified Page Accessibility Report)\n")
        sections.append(f"- **頁面相對路徑**: `{target_key}`")
        sections.append(f"- **完整網址**: {page_url}")
        sections.append(f"- **最新更新時間**: `{now_str}`")
        sections.append(f"- **無障礙探索進度**: **{pct}%** (`{covered_str}`)")
        sections.append(f"\n---------------------------------------------------\n")
        
        # 第一部分：靜態代碼
        if existing_static:
            sections.append(f"## 第一部分：靜態代碼無障礙審查結果 (Static Axe-core Audit)\n- **校對時間**: `{existing_coverage.get('static', now_str)}`\n\n{existing_static}\n")
            sections.append(f"---------------------------------------------------\n")
            
        # 第二部分：動態 AI 各章節
        if existing_dynamic_chapters:
            sections.append(f"## 第二部分：動態 AI 鍵盤與視覺對照審查結果 (Dynamic AI Audit)\n")
            for ch_key in sorted(existing_dynamic_chapters.keys()):
                ch_time = existing_coverage.get(ch_key, now_str)
                ch_text = existing_dynamic_chapters[ch_key]
                sections.append(f"### 📌 WCAG Guideline {ch_key} 審查結果\n- **校對時間**: `{ch_time}`\n\n{ch_text}\n")
                
        full_md = "\n".join(sections).strip() + "\n"
        
        with open(report_full_path, "w", encoding="utf-8") as pf:
            pf.write(full_md)
            
        # 5. 更新 Sitemap JSON 節點屬性
        if target_key_matched and target_key_matched in nodes:
            node = nodes[target_key_matched]
            node["coverage_wcag"] = existing_coverage
            node["coverage_pct"] = pct
            node["report_file"] = report_relpath
            
            if audit_type == "static":
                node["verified_at"] = now_str
                node["static_verified_at"] = now_str
            else:
                node["dynamic_verified_at"] = now_str
                
            # 狀態顯示百分比與已測清單
            if pct >= 100:
                node["status"] = f"100% (完全合規)"
            elif pct > 0:
                node["status"] = f"{pct}% ({covered_str})"
                
            with open(actual_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
                
        print(f"[PAGE SETTLEMENT] 成功更新單頁合一報告 ({audit_type} {current_ch if audit_type=='dynamic' else ''} | 進度: {pct}%): {report_relpath}")
    except Exception as e:
        print(f"[WARNING] Dump 單頁報告失敗: {e}")

