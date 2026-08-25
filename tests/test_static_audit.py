import pytest
from core.static_audit import (
    is_wcag_guideline_static,
    get_violation_wcag_level,
    get_wcag_conformance_level
)


def test_is_wcag_guideline_static():
    assert is_wcag_guideline_static("1.1") is True
    assert is_wcag_guideline_static("1.4") is True
    assert is_wcag_guideline_static("all") is True
    # 2.1 鍵盤無障礙為動態行為
    assert is_wcag_guideline_static("2.1") is False
    assert is_wcag_guideline_static("2.4") is False


def test_get_violation_wcag_level():
    assert get_violation_wcag_level(["cat.color", "wcag2a", "wcag143"]) == "A"
    assert get_violation_wcag_level(["wcag2aa"]) == "AA"
    assert get_violation_wcag_level(["wcag2aaa"]) == "AAA"
    assert get_violation_wcag_level(["best-practice"]) == "N/A"


def test_get_wcag_conformance_level():
    assert get_wcag_conformance_level("1.1") == "Level A"
    assert get_wcag_conformance_level("4.1") == "Level A / AA"
    assert get_wcag_conformance_level("99.9") == "N/A"
