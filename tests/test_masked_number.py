import pytest

from core.utils import is_masked_number, is_phone_like


@pytest.mark.parametrize("name", ["+55∙∙∙∙∙∙∙∙76", "+1 ∙∙∙ ∙∙∙-∙∙33", "+52∙∙∙∙∙∙∙∙∙45", "55••••76"])
def test_a_hidden_number_is_phone_like_not_a_name(name):
    assert is_masked_number(name)
    assert is_phone_like(name)


@pytest.mark.parametrize("name", ["Ana", "Ana • Silva", "gata-louca 🐱", "", None])
def test_a_name_is_not_a_masked_number(name):
    assert not is_masked_number(name)
