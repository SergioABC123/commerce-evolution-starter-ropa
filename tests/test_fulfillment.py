import pytest

from store.fulfillment import get_option, option_label, validate_address


@pytest.mark.parametrize("code,cost,requires_address", [
    ("standard", 9900, True),
    ("express", 19900, True),
    ("pickup", 0, False),
])
def test_option_rules(code, cost, requires_address):
    option = get_option(code)
    assert option.cost_cents == cost
    assert option.requires_address is requires_address
    assert validate_address(option, "  Test address  ") == (
        "Test address" if requires_address else ""
    )


@pytest.mark.parametrize("code", ["standard", "express"])
def test_shipping_requires_nonblank_address(code):
    with pytest.raises(ValueError, match="Shipping address is required"):
        validate_address(get_option(code), "  ")


def test_pickup_accepts_empty_address():
    assert validate_address(get_option("pickup"), "") == ""


def test_unknown_option_is_rejected():
    with pytest.raises(ValueError, match="Invalid fulfillment option"):
        get_option("unknown")
    assert option_label("retired") == "retired"
