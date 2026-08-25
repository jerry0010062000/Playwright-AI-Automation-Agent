import os
import json
import tempfile
import pytest

from core.sitemap_engine import (
    restructure_sitemap_hierarchy,
    save_sitemap_atomic,
    build_wcag_coverage_table
)
from core.models import SitemapNode, SitemapDocument


def test_restructure_sitemap_hierarchy_adds_intermediate_category():
    nodes = {
        "/": {"path": "/", "title": "首頁", "children": [], "parent": None},
        "/admin/settings/network": {"path": "/admin/settings/network", "title": "網路設定", "children": [], "parent": None},
    }
    
    result = restructure_sitemap_hierarchy(nodes)
    
    # 應自動補齊 /admin 與 /admin/settings 虛擬目錄節點
    assert "/admin" in result
    assert "/admin/settings" in result
    assert result["/admin"]["status"] == "CATEGORY"
    assert result["/admin/settings"]["status"] == "CATEGORY"
    assert result["/admin"]["title"] == "[目錄] Admin"
    
    # 檢查 parent/child 階層關聯
    assert result["/admin"]["parent"] == "/"
    assert "/admin" in result["/"]["children"]
    assert result["/admin/settings"]["parent"] == "/admin"
    assert "/admin/settings" in result["/admin"]["children"]
    assert result["/admin/settings/network"]["parent"] == "/admin/settings"
    assert "/admin/settings/network" in result["/admin/settings"]["children"]
    
    # 檢查葉節點與深度
    assert result["/"]["depth"] == 0
    assert result["/admin"]["depth"] == 1
    assert result["/admin/settings"]["depth"] == 2
    assert result["/admin/settings/network"]["depth"] == 3
    assert result["/admin/settings/network"]["is_leaf"] is True


def test_save_sitemap_atomic():
    with tempfile.TemporaryDirectory() as tmpdir:
        target_path = os.path.join(tmpdir, "test_sitemap.json")
        sample_data = {
            "base_path": "/",
            "total_pages": 1,
            "nodes": {
                "/": {"path": "/", "title": "首頁", "status": "OK"}
            }
        }
        
        success = save_sitemap_atomic(target_path, sample_data)
        assert success is True
        assert os.path.exists(target_path)
        
        with open(target_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["total_pages"] == 1
        assert "/" in loaded["nodes"]


def test_build_wcag_coverage_table():
    static_table = build_wcag_coverage_table("ALL")
    assert len(static_table) > 0
    assert any("WCAG 1.1.1" in line for line in static_table)
    
    dynamic_table = build_wcag_coverage_table("2.1")
    assert len(dynamic_table) > 0
    assert any("WCAG 2.1.1" in line for line in dynamic_table)


def test_sitemap_pydantic_validation():
    node = SitemapNode(path="/overview", title="總覽")
    assert node.status == "UNVERIFIED"
    assert node.is_leaf is True
    assert node.children == []
    
    doc = SitemapDocument(base_path="/", total_pages=1, nodes={"/overview": node})
    assert doc.total_pages == 1
    assert doc.nodes["/overview"].title == "總覽"
