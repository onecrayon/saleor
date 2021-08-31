from datetime import datetime
from typing import TYPE_CHECKING

import graphene

from firstech.SAP import models
from saleor.core.permissions import OrderPermissions
from saleor.graphql.core.mutations import ModelMutation
from saleor.graphql.core.types.common import OrderError
from saleor.graphql.SAP.types import SAPReturn
from saleor.order.models import Fulfillment as FulfillmentModel
from saleor.product.models import ProductVariant

from ....core.tracing import traced_atomic_transaction

if TYPE_CHECKING:
    from saleor.plugins.manager import PluginsManager
    from saleor.plugins.sap_orders.plugin import SAPPlugin


class UpsertSAPReturnDocument(ModelMutation):
    _return = graphene.Field(SAPReturn, description="The return that was upserted.")

    class Arguments:
        doc_entry = graphene.Int(
            required=True,
            description="The DocEntry value from SAP (primary key for SAP docs).",
        )

    class Meta:
        description = "Updates or creates returns for an order."
        model = models.SAPReturn
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    @traced_atomic_transaction()
    def perform_mutation(cls, _root, info, **data):
        manager: PluginsManager = info.context.plugins
        sap_plugin: SAPPlugin = manager.get_plugin(plugin_id="firstech.sap")
        if not sap_plugin:
            # the SAP plugin is inactive or doesn't exist
            return

        sap_return = sap_plugin.fetch_return(data["doc_entry"])

        # Try and figure out which fulfillment this goes to which is kept in the
        # BaseEntry field
        order = None
        try:
            delivery_doc_entry = sap_return.get("DocumentLines", [])[0]["BaseEntry"]
        except IndexError:
            pass
        else:
            if fulfillment := FulfillmentModel.objects.filter(
                private_metadata__doc_entry=delivery_doc_entry
            ).first():
                order = fulfillment.order

        business_partner = models.BusinessPartner.objects.get(
            sap_bp_code=sap_return["CardCode"]
        )

        _return, _ = models.SAPReturn.objects.update_or_create(
            business_partner=business_partner,
            doc_entry=sap_return["DocEntry"],
            defaults={
                "create_date": datetime.strptime(sap_return.get("DocDate"), "%Y-%m-%d"),
                "order": order,
                "remarks": sap_return.get("Comments"),
                "purchase_order": sap_return.get("NumAtCard"),
            },
        )

        for line in sap_return["DocumentLines"]:
            variant = ProductVariant.objects.get(sku=line["ItemCode"])
            models.SAPReturnLine.objects.update_or_create(
                sap_return=_return,
                product_variant=variant,
                defaults={
                    "quantity": line["Quantity"],
                    "unit_price_amount": line["Price"],
                    "currency": "USD",
                },
            )

        return UpsertSAPReturnDocument(_return=_return)
