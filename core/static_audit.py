import os
import json
from config import MAX_CRAWL_PAGES
from reporting.single_page_report import dump_single_page_settlement_report

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


def run_axe_audit(page) -> dict:
    """
    於 Playwright 頁面上注入並執行 Axe-core 腳本進行靜態 DOM 無障礙檢測
    """
    axe_script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "node_modules", "axe-core", "axe.min.js")
    if not os.path.exists(axe_script_path):
        # 備用備查目錄
        axe_script_path = os.path.join("node_modules", "axe-core", "axe.min.js")
        
    if os.path.exists(axe_script_path):
        page.add_script_tag(path=axe_script_path)
    else:
        # CDN 注入降級
        page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.7.2/axe.min.js")
        
    axe_run_script = """
    async () => {
        return await axe.run({
            runOnly: {
                type: 'tag',
                values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22a', 'wcag22aa', 'best-practice']
            }
        });
    }
    """
    return page.evaluate(axe_run_script)


def perform_local_site_audit(page, base_url: str, wcag_ver: str, sitemap_path: str = None) -> dict:
    """
    對目標網址（包含完整 Sitemap 所有內部連結）進行全站 0-Token 本地 Axe-core 代碼審查
    """
    print(f"\n[*] 啟動全站 0-Token 本地 Axe-core 代碼審查 (目標: {base_url}, 規範: {wcag_ver})...")
    
    # 全量 Sitemap URL 載入 (靜態無障礙全站掃描保證不裁剪)
    urls = []
    if sitemap_path:
        actual_sitemap_path = sitemap_path
        if not os.path.exists(actual_sitemap_path):
            alt = os.path.join("sitemaps", os.path.basename(sitemap_path))
            if os.path.exists(alt):
                actual_sitemap_path = alt
                
        if os.path.exists(actual_sitemap_path):
            try:
                with open(actual_sitemap_path, "r", encoding="utf-8") as f:
                    sdata = json.load(f)
                if isinstance(sdata, dict) and "nodes" in sdata:
                    base_prefix = base_url.rstrip("/")
                    for node_path in sdata["nodes"].keys():
                        if node_path == "/":
                            urls.append(base_prefix + "/")
                        else:
                            urls.append(base_prefix + node_path)
                    print(f"[✓] 成功自 Sitemap ({actual_sitemap_path}) 載入全站 {len(urls)} 個完整 URL 進行 0-Token 代碼掃描！")
                elif isinstance(sdata, list):
                    urls = sdata
            except Exception as sm_err:
                print(f"[WARNING] 讀取 Sitemap 失敗: {sm_err}")

    if not urls:
        get_links_script = """
        (() => {
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            const urls = [...new Set(anchors.map(a => a.href).filter(href => {
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

    urls = list(set(urls))[:MAX_CRAWL_PAGES]
    print(f"[*] 已規劃巡檢以下 {len(urls)} 個內部頁面: {urls}")
    
    audit_results = {}
    total_violations = 0
    clean_ver = wcag_ver.replace(".", "")
    target_tag_prefix = f"wcag{clean_ver}"
    
    for u in urls:
        print(f"[*] 正在本地檢測頁面: {u}")
        try:
            nav_success = False
            try:
                from urllib.parse import urlparse
                parsed_url = urlparse(u)
                path = parsed_url.path
                if path and path != "/" and "login" not in path.lower():
                    link = page.query_selector(f"a[href$='{path}'], a[href='{path}']")
                    if link and link.is_visible():
                        try:
                            link.click(timeout=2000)
                        except Exception:
                            try:
                                link.click(force=True, timeout=1000)
                            except Exception:
                                pass
                        page.wait_for_timeout(1000)
                        if "login" not in page.url.lower():
                            nav_success = True
            except Exception:
                pass
                
            if not nav_success:
                try:
                    page.goto(u, wait_until="domcontentloaded")
                    page.wait_for_timeout(1000)
                except Exception as goto_err:
                    print(f"[WARNING] 導航至 {u} 失敗: {goto_err}")
            
            # Session 保障衛士 (Session Guard)
            pw_input = page.query_selector("input[type='password']")
            if ("login" in page.url.lower() or (pw_input and pw_input.is_visible())) and "login" not in u.lower():
                print(f"  ⚠️ [SESSION GUARD] 檢測頁面 {u} 時發現 Session 掉線！啟動自動重新導向...")
                page.goto(u, wait_until="domcontentloaded")
                page.wait_for_timeout(1000)
            
            title = "N/A"
            html_len = 0
            elements_count = 0
            try:
                title = page.title()
                html_len = len(page.content())
                elements_count = page.evaluate("document.getElementsByTagName('*').length")
            except Exception:
                pass
                
            axe_res = run_axe_audit(page)
            violations = axe_res.get("violations", [])
            
            matched_violations = []
            if wcag_ver.upper() in ["ALL", "STATIC_ALL"]:
                matched_violations = violations
            else:
                for vio in violations:
                    is_match = False
                    for tag in vio.get("tags", []):
                        if tag.startswith(target_tag_prefix):
                            is_match = True
                            break
                    if is_match:
                        matched_violations.append(vio)
            
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
            
            # 建立該單頁的靜態 Axe-core 審查報告區塊並寫入單頁檔案中
            static_page_md = f"- **頁面標題**: `{title}`\n" \
                             f"- **DOM 元素數**: `{elements_count}`\n" \
                             f"- **檢測狀態**: `{'✅ PASS' if not matched_violations else '❌ FAIL'}`\n" \
                             f"- **發現靜態違規數**: `{len(matched_violations)}` 處\n\n"
            
            if matched_violations:
                static_page_md += "### ❌ 本頁面靜態代碼違規與修復建議列表\n\n"
                for v_idx, vio in enumerate(matched_violations):
                    v_impact = vio.get("impact", "N/A").upper()
                    v_id = vio.get("id", "N/A")
                    v_help = vio.get("help", "")
                    v_desc = vio.get("description", "")
                    v_nodes = vio.get("nodes", [])
                    v_level = get_violation_wcag_level(vio.get("tags", []))
                    
                    static_page_md += f"#### {v_idx + 1}. [{v_impact}] {v_id} - {v_help} (Level {v_level})\n"
                    static_page_md += f"- **描述**: {v_desc}\n"
                    static_page_md += f"- **受影響 DOM 節點數量**: `{len(v_nodes)}`\n"
                    if v_nodes:
                        static_page_md += f"- **受影響 HTML 選擇器與修復指引**:\n"
                        for n_idx, node in enumerate(v_nodes[:3]):
                            selector = ", ".join(node.get("target", []))
                            summary = node.get("failureSummary", "")
                            static_page_md += f"  - 節點 {n_idx + 1}: `{selector}`\n"
                            static_page_md += f"    - 修復建議: {summary}\n"
                    static_page_md += "\n"
            else:
                static_page_md += "🎉 **此頁面未發現任何靜態代碼層面之無障礙違規項目 (PASS)**。\n"
                
            dump_single_page_settlement_report(sitemap_path, u, static_page_md, audit_type="static")
            
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
    透過輕量級 AI 呼叫，評估當前任務是否只需使用 Axe-core 代碼審查工具即可解決
    """
    print("[*] Evaluating if task can be resolved using local Axe-core tool (code audit)...")
    prompt = (
        "你是一個 Web 無障礙檢測架構分析專家。請分析以下使用者要求及注入的 WCAG 2.2 規範。\n"
        "判斷該任務「是否只需要檢查 HTML 代碼結構、屬性（如是否有 alt、ID是否唯一、ARIA是否正確）」，也就是說「完全不需要進行任何滑鼠點擊、鍵盤輸入、視覺對比度確認或動態互動，只需使用代碼檢測工具（如 Axe-core）即可完全解決」。\n\n"
        f"【使用者任務】:\n{task}\n\n"
        f"【任務說明/規範】:\n{extra_instructions[:500]}\n\n"
        "請只回答 JSON 格式:\n"
        "{\n"
        '  "use_static_axe": true/false,\n'
        '  "wcag_ver": "1.1" (或 1.2, 1.3, 1.4, 2.1, 2.2, 2.4, 3.1, 4.1 等),\n'
        '  "reason": "簡短判定原因"\n'
        "}"
    )
    
    try:
        if model.lower().startswith("claude-"):
            from claude_client import ClaudeAgent
            agent = ClaudeAgent(model=model)
        else:
            from gemini_client import GeminiAgent
            agent = GeminiAgent(model=model)
            
        res = agent.generate_quick_response(prompt)
        start_idx = res.find("{")
        end_idx = res.rfind("}")
        if start_idx != -1 and end_idx != -1:
            json_str = res[start_idx:end_idx+1]
            data = json.loads(json_str)
            return data.get("use_static_axe", False), data.get("wcag_ver", "1.1"), data.get("reason", "")
    except Exception as e:
        print(f"[WARNING] 評估任務類型出錯: {e}")
        
    return False, "1.1", "Evaluation fallback to dynamic"
