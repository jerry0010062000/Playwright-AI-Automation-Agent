import os
import json
from core.sitemap_engine import build_wcag_coverage_table

def format_static_audit_summary_for_ai(raw_results: dict, wcag_ver: str) -> str:
    """
    將 Axe-core 的靜態檢測數據格式化為適合 AI 解讀與總結的文本
    """
    summary_for_ai = []
    summary_for_ai.append("【WCAG 2.2 官方涵蓋條款與 3 位數 Success Criteria 對照基準】:")
    summary_for_ai.extend(build_wcag_coverage_table(wcag_ver))
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
                    
    return "\n".join(summary_for_ai)


def generate_master_site_report(sitemap_path: str, output_report_path: str):
    """
    根據 Sitemap 的目前所有頁面狀態，產出全站總合規率統計與 master_report.md
    """
    if not os.path.exists(sitemap_path):
        return
        
    try:
        with open(sitemap_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        nodes = data.get("nodes", {})
        total_nodes = len(nodes)
        static_verified = 0
        dynamic_verified = 0
        
        for k, v in nodes.items():
            if v.get("verified_at"):
                static_verified += 1
            if v.get("dynamic_verified_at"):
                dynamic_verified += 1
                
        master_content = (
            f"# 網站全站無障礙巡檢 Master 總結報告\n\n"
            f"- **採用 Sitemap**: `{sitemap_path}`\n"
            f"- **全站已知總頁數**: `{total_nodes}` 頁\n"
            f"- **已完成靜態校對頁數**: `{static_verified}` / `{total_nodes}` 頁\n"
            f"- **已完成動態 AI 校對頁數**: `{dynamic_verified}` / `{total_nodes}` 頁\n\n"
            f"## 頁面目錄與單頁報告索引\n\n"
            f"| 頁面相對路徑 | 標題 | 靜態校對時間 | 動態 AI 校對時間 | 單頁報告連結 |\n"
            f"| :--- | :--- | :--- | :--- | :--- |\n"
        )
        
        for path, info in nodes.items():
            s_time = info.get("verified_at", "-")
            d_time = info.get("dynamic_verified_at", "-")
            rep_file = info.get("report_file", "")
            rep_link = f"[查看報告]({rep_file})" if rep_file else "待探索"
            title = info.get("title", "N/A")
            master_content += f"| `{path}` | {title} | `{s_time}` | `{d_time}` | {rep_link} |\n"
            
        with open(output_report_path, "w", encoding="utf-8") as mf:
            mf.write(master_content)
            
        print(f"[MASTER REPORT] 成功生成全站總統計報告: {output_report_path}")
    except Exception as e:
        print(f"[WARNING] 產生 Master 總報告出錯: {e}")
