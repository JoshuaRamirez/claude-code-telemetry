"""Tests for calculate_cost() -- pure function, no mocking needed.

Target: hooks/db_logger.py:403-408
"""

import pytest

from hooks.db_logger import calculate_cost, MODEL_PRICING


pytestmark = pytest.mark.unit


class TestKnownModels:
    @pytest.mark.parametrize("model,input_price,output_price", [
        ('claude-opus-4-5-20251101', 15.0, 75.0),
        ('claude-sonnet-4-20250514', 3.0, 15.0),
        ('claude-haiku-3-5-20241022', 0.80, 4.0),
    ])
    def test_known_model_pricing(self, model, input_price, output_price):
        cost = calculate_cost(model, 1_000_000, 1_000_000)
        expected = input_price + output_price
        assert abs(cost - expected) < 0.001


class TestUnknownModel:
    def test_unknown_model_uses_default(self):
        cost = calculate_cost('unknown-model-v99', 1_000_000, 1_000_000)
        default = MODEL_PRICING['default']
        expected = default['input'] + default['output']
        assert abs(cost - expected) < 0.001


class TestEdgeCases:
    def test_zero_tokens(self):
        assert calculate_cost('claude-sonnet-4-20250514', 0, 0) == 0.0

    def test_none_tokens_treated_as_zero(self):
        """The `or 0` path in the function handles None gracefully."""
        assert calculate_cost('claude-sonnet-4-20250514', None, None) == 0.0
