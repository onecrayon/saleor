from collections import defaultdict

from firstech.SAP.models import BusinessPartner
from saleor.order.models import Order
from ..core.dataloaders import DataLoader


class OrdersByBusinessPartnerLoader(DataLoader):
    context_key = "order_by_business_partner"

    def batch_load(self, keys):
        # keys are the ids of business partners
        bp_card_code_cache = {}
        for id, card_code in BusinessPartner.objects.filter(id__in=keys).values_list(
            "id", "sap_bp_code"
        ):
            bp_card_code_cache[card_code] = id

        orders = Order.objects.filter(
            private_metadata__sap_bp_code__in=bp_card_code_cache.keys()
        )
        orders_by_bp_map = defaultdict(list)
        for order in orders:
            bp_id = bp_card_code_cache[order.private_metadata["sap_bp_code"]]
            orders_by_bp_map[bp_id].append(order)
        return [orders_by_bp_map.get(bp_id, []) for bp_id in keys]
