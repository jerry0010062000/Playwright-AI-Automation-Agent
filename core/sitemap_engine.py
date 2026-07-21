import os
import json
import datetime
from urllib.parse import urlparse
from reporting.single_page_report import get_map_records_dir, get_page_report_relpath

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
        parsed = urlparse(page_url)
        rel_path = parsed.path or "/"
        
        with open(actual_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        nodes = data.get("nodes", {})
        target_key_matched = None
        for key in nodes:
            if key == rel_path or key.rstrip("/") == rel_path.rstrip("/") or (key.endswith("/index.html") and key.replace("/index.html", "") == rel_path.rstrip("/")):
                target_key_matched = key
                break
                
        if target_key_matched and target_key_matched in nodes:
            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            report_relpath = get_page_report_relpath(actual_path, target_key_matched)
            
            map_dir, pages_dir = get_map_records_dir(actual_path)
            report_full_path = os.path.join(os.getcwd(), report_relpath)
            
            if not os.path.exists(report_full_path):
                with open(report_full_path, "w", encoding="utf-8") as pf:
                    pf.write(f"# 📝 頁面無障礙巡檢報告 (Page Audit Report)\n\n")
                    pf.write(f"- **頁面相對路徑**: `{target_key_matched}`\n")
                    pf.write(f"- **完整網址**: {page_url}\n")
                    pf.write(f"- **校對類型**: 🤖 動態 AI 巡檢 (Dynamic AI Audit)\n")
                    pf.write(f"- **校對時間**: `{now_str}`\n\n")
                    pf.write(f"## 📊 檢測結論與記錄\n此頁面已完成動態 AI 鍵盤與視覺焦點無障礙走訪驗證。\n")

            nodes[target_key_matched]["dynamic_verified_at"] = now_str
            nodes[target_key_matched]["report_file"] = report_relpath
            with open(actual_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print(f"[MAP SYNC] 🤖 成功寫入動態校對 Checkpoint: [{target_key_matched}] ({now_str})")
    except Exception as e:
        pass


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
            lines.append("| **WCAG 1.4.3** | 對比度 (最小門檻 4.5:1 / 3:1) | Level AA | 檢查文字與背景對比度 |")
        elif clean.startswith("21"):
            lines.append("| **WCAG 2.1.1** | 鍵盤操作 (Keyboard Accessible) | Level A | 檢查所有功能是否可透過鍵盤操作 |")
            lines.append("| **WCAG 2.1.2** | 無鍵盤陷阱 (No Keyboard Trap) | Level A | 確保鍵盤焦點不會受陷 |")
        elif clean.startswith("24"):
            lines.append("| **WCAG 2.4.7** | 焦點可見 (Focus Visible Outline) | Level AA | 檢查元件焦點環外框顯影 |")
        elif clean.startswith("41"):
            lines.append("| **WCAG 4.1.2** | 名稱、角色與數值 (Name, Role, Value) | Level A | 檢查 HTML/ARIA 語意名稱屬性 |")
        lines.append("")
        
    return lines
