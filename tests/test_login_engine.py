import pytest
from core.prompt_builder import get_interaction_tokens


def test_login_engine_token_parsing():
    class MockUsage:
        input_tokens = 500
        output_tokens = 120
        cache_read_input_tokens = 300
        cache_creation_input_tokens = 200

    class MockInteraction:
        usage = MockUsage()

    tokens = get_interaction_tokens(MockInteraction())
    assert tokens["input"] == 500
    assert tokens["output"] == 120
    assert tokens["cache_read_input_tokens"] == 300
    assert tokens["cache_creation_input_tokens"] == 200
    assert tokens["total"] == 620
