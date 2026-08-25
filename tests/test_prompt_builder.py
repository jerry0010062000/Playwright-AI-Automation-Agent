import pytest
from core.prompt_builder import (
    get_interaction_tokens, 
    build_wcag_prompt, 
    resolve_model_rates, 
    BASE_7_7_PRICING
)


def test_get_interaction_tokens_with_dict():
    class DummyInteraction:
        usage = {
            "input_tokens": 120,
            "output_tokens": 45,
            "cache_read_input_tokens": 80,
            "cache_creation_input_tokens": 20,
            "total_tokens": 165
        }
    
    tokens = get_interaction_tokens(DummyInteraction())
    assert tokens["input"] == 120
    assert tokens["output"] == 45
    assert tokens["cache_read_input_tokens"] == 80
    assert tokens["cache_creation_input_tokens"] == 20


def test_build_wcag_prompt():
    full_prompt, rule_text = build_wcag_prompt("檢測網站無障礙", "2.1")
    assert "檢測網站無障礙" in full_prompt
    assert "WCAG" in full_prompt


def test_resolve_model_rates_base_7_7_fallback():
    # 測試標準已知模型
    rates, key, source = resolve_model_rates("claude-sonnet-5")
    assert rates["input"] > 0
    assert rates["output"] > 0
    assert "claude-sonnet" in key.lower()
    
    # 測試 Gemini 模型
    rates_gemini, key_gemini, _ = resolve_model_rates("gemini-2.5-flash")
    assert rates_gemini["input"] == 0.075 or rates_gemini["input"] > 0

    # 測試未知模型降級到 default
    rates_unknown, key_unknown, source_unknown = resolve_model_rates("unknown-custom-model-xyz")
    assert rates_unknown["input"] == BASE_7_7_PRICING["default"]["input"] or rates_unknown["input"] > 0

