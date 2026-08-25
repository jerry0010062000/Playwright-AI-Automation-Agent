"""
ASACC Core Data Models
Pydantic v2 models for Sitemap nodes and document validation.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class SitemapNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    path: str
    title: str = "未命名頁面"
    parent: Optional[str] = None
    children: List[str] = Field(default_factory=list)
    is_leaf: bool = True
    depth: int = 0
    status: str = "UNVERIFIED"
    error: bool = False
    initialized: bool = True
    initialized_at: Optional[str] = None
    dynamic_verified_at: Optional[str] = None
    static_verified_at: Optional[str] = None
    report_file: Optional[str] = None
    axe_audit: Optional[Dict[str, Any]] = None
    coverage_wcag: Optional[Dict[str, Any]] = None


class SitemapDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    base_path: str = "/"
    total_pages: int = 1
    target_url: Optional[str] = None
    last_updated: Optional[str] = None
    nodes: Dict[str, SitemapNode] = Field(default_factory=dict)
