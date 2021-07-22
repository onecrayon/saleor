from dataclasses import dataclass
from typing import Any
from ..base_plugin import BasePlugin, ConfigurationTypeField
from ...warehouse.models import Backorder


@dataclass
class BackordersConfiguration:
    backorders_enabled: bool
    backorder_limit: int


class BackordersPlugin(BasePlugin):
    PLUGIN_ID = "firstech.backorders"
    PLUGIN_NAME = "Backorders"
    DEFAULT_ACTIVE = False
    CONFIGURATION_PER_CHANNEL = True

    CONFIG_STRUCTURE = {
        "backorders_enabled": {
            "type": ConfigurationTypeField.BOOLEAN,
            "help_text": "Whether or not to enable backorders for checkouts and orders",
            "label": "Backorders Enabled",
        },
    }

    DEFAULT_CONFIGURATION = [
        {"name": "backorders_enabled", "value": False},
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Convert to dict to easier take config elements
        configuration = {item["name"]: item["value"] for item in self.configuration}

        self.config = BackordersConfiguration(
            backorders_enabled=configuration["backorders_enabled"],
        )

    def is_backorder_allowed(self, previous_value):
        return self.config.backorders_enabled

    def order_cancelled(self, order: "Order", previous_value: Any) -> Any:
        """Trigger when order is cancelled.

        Overwrite this method if you need to trigger specific logic when an order is
        canceled.
        """
        backorders = Backorder.objects.filter(
            order_line__order=order, quantity__gt=0
        ).select_for_update(of=("self",))
        backorders.update(quantity=0)
