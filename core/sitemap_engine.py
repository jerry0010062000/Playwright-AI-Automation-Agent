import os
import json
import datetime
import urllib.parse
from urllib.parse import urlparse
from reporting.single_page_report import get_map_records_dir, get_page_report_relpath


def restructure_sitemap_hierarchy(nodes: dict) -> dict:
    """
    重構 Sitemap 節點階層，自動補齊中間路徑的虛擬 CATEGORY 目錄節點，
    並重構 parent / children 關聯，使視覺化樹狀圖具有分支深度感。
    """
    # 1. 蒐集並補齊所有中間節點
    original_paths = list(nodes.keys())
    
    for path in original_paths:
        if path == "/":
            continue
            
        # 移去前後的斜線並分割路徑
        parts = [p for p in path.strip("/").split("/") if p]
        
        # 逐層建立中間路徑
        for i in range(1, len(parts)):
            intermediate_parts = parts[:i]
            intermediate_path = "/" + "/".join(intermediate_parts)
            
            # 若中間路徑節點不存在，則新增為 CATEGORY 節點
            if intermediate_path not in nodes:
                part_name = intermediate_parts[-1]
                title_name = part_name.capitalize() if not part_name.endswith(('.htm', '.html')) else part_name
                
                nodes[intermediate_path] = {
                    "path": intermediate_path,
                    "title": f"📁 {title_name}",
                    "parent": None,
                    "children": [],
                    "is_leaf": False,
                    "depth": len(intermediate_parts),
                    "status": "CATEGORY",
                    "error": False,
                    "initialized": True,
                    "initialized_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }

    # 2. 清空所有節點的 children，準備重新建立關聯
    for path, node in nodes.items():
        node["children"] = []
        node["parent"] = None

    # 3. 重新建立 parent 和 children 關係
    for path, node in nodes.items():
        if path == "/":
            continue
            
        parts = [p for p in path.strip("/").split("/") if p]
        if len(parts) == 1:
            parent_path = "/"
        else:
            parent_path = "/" + "/".join(parts[:-1])
            
        if parent_path in nodes:
            node["parent"] = parent_path
            if path not in nodes[parent_path]["children"]:
                nodes[parent_path]["children"].append(path)
                
    # 4. 重新計算 is_leaf 和 depth
    for path, node in nodes.items():
        if path == "/":
            node["depth"] = 0
            node["parent"] = None
        else:
            parts = [p for p in path.strip("/").split("/") if p]
            node["depth"] = len(parts)
            
        node["is_leaf"] = (len(node.get("children", [])) == 0)
        
    return nodes


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
    print(f"[*] 啟動地圖動態走訪校對與更新引擎 (Sitemap Sync Engine)...")
    print(f"  - 目標基礎網址: {base_url}")
    print(f"  - 目標地圖檔案: {sitemap_path}")
    if max_pages:
        print(f"  - 本次設定走訪上限: {max_pages} 頁 (避免超過回合數/Token庫存)")
    
    # 若地圖不存在，自動創建最小地圖
    if not os.path.exists(sitemap_path):
        print(f"[🌱] 地圖檔案不存在，自動創建最小地圖...")
        
        sitemap_dir = os.path.dirname(sitemap_path)
        if sitemap_dir and not os.path.exists(sitemap_dir):
            os.makedirs(sitemap_dir, exist_ok=True)
        
        parsed_url = urllib.parse.urlparse(base_url)
        minimal_sitemap = {
            "base_path": "/",
            "total_pages": 1,
            "target_url": base_url,
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
    
    # 提取語言過濾配置
    scan_languages = sitemap_data.get("scan_languages", None)
    if scan_languages:
        print(f"[📌] 語言過濾已啟用：只掃描 {scan_languages} 語言版本")
    
    # 從 sitemap metadata 讀取認證資訊
    if not username:
        username = sitemap_data.get("default_username", "")
    if not password:
        password = sitemap_data.get("default_password", "")

    # 清理地圖中的靜態資源節點
    static_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', 
                        '.css', '.js', '.woff', '.woff2', '.ttf', '.eot', 
                        '.pdf', '.zip', '.mp4', '.mp3', '.wav')
    removed_static_resources = []
    for path in list(nodes.keys()):
        if path.lower().endswith(static_extensions):
            parent_path = nodes[path].get("parent")
            if parent_path and parent_path in nodes:
                if path in nodes[parent_path].get("children", []):
                    nodes[parent_path]["children"].remove(path)
            del nodes[path]
            removed_static_resources.append(path)
    
    if removed_static_resources:
        print(f"[🧹] 清理了 {len(removed_static_resources)} 個靜態資源節點 (圖片、CSS、JS 等)")
    
    # 清理後重新獲取節點列表 (排除虛擬目錄分類節點 CATEGORY)
    unverified_paths = [p for p, n in nodes.items() if not n.get("initialized") and n.get("status") != "CATEGORY"]
    verified_paths = [p for p, n in nodes.items() if n.get("initialized") and n.get("status") != "CATEGORY"]
    
    # 將根節點和主要頁面優先排序
    priority_paths = ["/", "/login", "/overview", "/advanced"]
    priority_queue = [p for p in priority_paths if p in verified_paths]
    other_verified = [p for p in verified_paths if p not in priority_paths]

    if verified_paths and unverified_paths:
        print(f"[*] [SITEMAP RESUME] 檢測到中斷點：已驗證 {len(verified_paths)} 頁，將優先續接剩餘未驗證的 {len(unverified_paths)} 頁！")
        queue = unverified_paths + priority_queue + other_verified
    elif unverified_paths:
        queue = unverified_paths
    else:
        print(f"[*] [SITEMAP FULL RE-VERIFY] 全站所有 {len(nodes)} 頁先前皆已校對完成，開始新一輪複查...")
        queue = priority_queue + other_verified

    visited = set()
    discovered_count = 0
    dead_count = 0
    updated_titles = 0
    visited_in_run = 0
    dead_link_patterns = set()
    
    total_to_scan = len(queue)
    estimated_time_seconds = total_to_scan * 1.5
    estimated_minutes = int(estimated_time_seconds / 60)
    print(f"[⏱️] 預計掃描時間: 約 {estimated_minutes} 分鐘 ({total_to_scan} 頁 × 1.5 秒/頁)")

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
        
        progress_pct = int((visited_in_run / total_to_scan) * 100) if total_to_scan > 0 else 0
        print(f"[*] [SITEMAP VERIFY] [{visited_in_run}/{total_to_scan}] ({progress_pct}%) 正在走訪頁面: {rel_path} -> {full_url}")

        try:
            response = page.goto(full_url, timeout=12000, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            
            actual_url = page.url.lower()
            expected_url = full_url.lower()
            
            # 檢查是否被跳轉到登入頁（會話超時）
            if actual_url != expected_url and "login" in actual_url and "login/status" not in actual_url and "login/clienttime" not in actual_url:
                print(f"[⚠️] 檢測到頁面跳轉至登入頁 ({rel_path} → {page.url})")
                print(f"[⚠️] 會話已失效，正在重新登入...")
                
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
                            response = page.goto(full_url, timeout=12000, wait_until="domcontentloaded")
                            page.wait_for_timeout(1000)
                        else:
                            print(f"[✗] 重新登入失敗！停止掃描以避免產生虛假死鏈。")
                            break
                    except Exception as e:
                        print(f"[✗] 重新登入錯誤: {e}。停止掃描。")
                        break
                else:
                    print(f"[✗] 缺少認證資訊，無法自動重新登入。停止掃描。")
                    break
            
            # 滾動頁面以觸發懶加載內容
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(300)
                page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass
            
            status_code = response.status if response else 200

            # 檢查前端 Client-side SPA 404
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
                    print(f"  📁 檢測到目錄節點為導覽目錄 (HTTP {status_code}{'，前端 404' if is_client_side_404 else ''})。標記為導覽目錄。")
                    nodes[rel_path]["status"] = "CATEGORY"
                    nodes[rel_path]["error"] = False
                    nodes[rel_path]["initialized"] = True
                    nodes[rel_path]["initialized_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    continue
                else:
                    print(f"  ⚠️ 檢測到實體死鏈 (HTTP {status_code}{'，前端 404' if is_client_side_404 else ''})。自地圖中移除並自癒結構...")
                    
                    if rel_path.startswith("../"):
                        parts = rel_path.split("/")
                        if len(parts) >= 3:
                            pattern = "/".join(parts[:3]) + "/"
                            dead_link_patterns.add(pattern)
                            print(f"  📝 記錄死鏈模式: {pattern} (後續將自動跳過相似路徑)")
                    
                    parent_path = nodes[rel_path].get("parent")
                    if parent_path in nodes:
                        if rel_path in nodes[parent_path].get("children", []):
                            try:
                                nodes[parent_path]["children"].remove(rel_path)
                            except Exception:
                                pass
                                
                    for child_path in nodes[rel_path].get("children", []):
                        if child_path in nodes:
                            nodes[child_path]["parent"] = parent_path
                            if parent_path in nodes:
                                if "children" not in nodes[parent_path]:
                                    nodes[parent_path]["children"] = []
                                if child_path not in nodes[parent_path]["children"]:
                                    nodes[parent_path]["children"].append(child_path)
                                    
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

                extract_links_script = r"""
                (() => {
                    const links = new Set();
                    
                    document.querySelectorAll('a[href]').forEach(a => {
                        links.add(a.href);
                    });
                    
                    document.querySelectorAll('[href]').forEach(el => {
                        let absoluteUrl;
                        if (el.href) {
                            absoluteUrl = el.href;
                        } else {
                            try {
                                const relativeUrl = el.getAttribute('href');
                                absoluteUrl = new URL(relativeUrl, window.location.href).href;
                            } catch(e) {
                                return;
                            }
                        }
                        links.add(absoluteUrl);
                    });
                    
                    document.querySelectorAll('button, [role="button"], [onclick]').forEach(el => {
                        const onclick = el.getAttribute('onclick') || el.textContent;
                        if (onclick) {
                            const pathMatch = onclick.match(/['"]\/[^'"]*['"]/) || 
                                            onclick.match(/navigate.*?['"]\/[^'"]*['"]/) ||
                                            onclick.match(/to:\s*['"]\/[^'"]*['"]/)
                            if (pathMatch && pathMatch[0]) {
                                const path = pathMatch[0].replace(/['"]/g, '');
                                links.add(window.location.origin + path);
                            }
                        }
                    });
                    
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

                    is_json_endpoint = '.json' in child_rel.lower().split('?')[0]
                    is_invalid_relative = (
                        child_rel != "/" and 
                        not child_rel.startswith("/") and 
                        "/" in child_rel and
                        not child_rel.startswith("http")
                    )
                    
                    is_unwanted_lang = False
                    if scan_languages:
                        if '?lang=' in child_rel or '&lang=' in child_rel:
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
                    
                    if child_rel not in visited and child_rel not in queue:
                        queue.append(child_rel)

            nodes[rel_path]["initialized_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        except Exception as err:
            print(f"  ⚠️ 走訪頁面失敗 {rel_path}: {err}")
            nodes[rel_path]["status"] = "ERROR"
            nodes[rel_path]["error"] = str(err)
            nodes[rel_path]["initialized_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            dead_count += 1

        if visited_in_run % 5 == 0:
            try:
                nodes = restructure_sitemap_hierarchy(nodes)
                sitemap_data["nodes"] = nodes
                sitemap_data["total_pages"] = len(nodes)
                sitemap_data["last_verified"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(sitemap_path, "w", encoding="utf-8") as sf:
                    json.dump(sitemap_data, sf, ensure_ascii=False, indent=2)
            except Exception:
                pass

    nodes = restructure_sitemap_hierarchy(nodes)

    sitemap_data["total_pages"] = len(nodes)
    sitemap_data["last_verified"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sitemap_data["nodes"] = nodes

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
