"""Fulfillment policy: one source of truth for available delivery options."""
from dataclasses import dataclass

STANDARD = "standard"


@dataclass(frozen=True)
class FulfillmentOption:
    code: str
    label: str
    cost_cents: int
    requires_address: bool


OPTIONS = (
    FulfillmentOption(STANDARD, "Standard Shipping", 9_900, True),
    FulfillmentOption("express", "Express Shipping", 19_900, True),
    FulfillmentOption("pickup", "Store Pickup", 0, False),
)


def get_option(code: str) -> FulfillmentOption:
    for option in OPTIONS:
        if option.code == code:
            return option
    raise ValueError("Invalid fulfillment option.")


def validate_address(option: FulfillmentOption, address: str) -> str:
    if not option.requires_address:
        return ""
    address = address.strip()
    if not address:
        raise ValueError("Shipping address is required for the selected option.")
    return address


def option_label(code: str) -> str:
    """Keep historical order details readable if an option is retired."""
    try:
        return get_option(code).label
    except ValueError:
        return code
