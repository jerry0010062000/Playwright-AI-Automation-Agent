import os
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
                    if "## 第一部分：靜態代碼無障礙審查" in old_text and audit_type == "dynamic":
                        parts = old_text.split("## 第二部分：動態 AI")
                        existing_static_content = parts[0]
                    elif "## ⚡ 第一部分：靜態代碼無障礙審查" in old_text and audit_type == "dynamic":
                        parts = old_text.split("## 🤖 第二部分：動態 AI")
                        existing_static_content = parts[0]
            except Exception:
                pass

        if audit_type == "static":
            header_type_str = "本地靜態代碼巡檢 (Static Audit)"
            section_block = f"## 第一部分：靜態代碼無障礙審查結果 (Static Axe-core Audit)\n- **校對時間**: `{now_str}`\n\n{content_text}\n"
        elif audit_type == "dynamic":
            header_type_str = "動態 AI 鍵盤與視覺巡檢 (Dynamic AI Audit)"
            section_block = f"## 第二部分：動態 AI 鍵盤與視覺對照審查結果 (Dynamic AI Audit)\n- **校對時間**: `{now_str}`\n\n{content_text}\n"
        else:
            header_type_str = "雙模合一巡檢 (Hybrid Audit)"
            section_block = content_text

        if existing_static_content and audit_type == "dynamic":
            full_md_content = existing_static_content.strip() + "\n\n---------------------------------------------------\n\n" + section_block
        else:
            full_md_content = f"# 頁面無障礙綜合巡檢報告 (Unified Page Accessibility Report)\n\n" \
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
                
        print(f"[PAGE SETTLEMENT] 成功寫入單頁合一報告 ({audit_type}): {report_relpath}")
    except Exception as e:
        print(f"[WARNING] Dump 單頁報告失敗: {e}")
