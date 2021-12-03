from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import graphene
from django.core.exceptions import ValidationError

from firstech.SAP import models
from saleor.core.permissions import OrderPermissions
from saleor.graphql.core.mutations import ModelMutation
from saleor.graphql.core.types.common import OrderError
from saleor.graphql.SAP.types import SAPCreditMemo
from firstech.SAP.models import SAPReturn
from saleor.product.models import ProductVariant

from ....core.tracing import traced_atomic_transaction

if TYPE_CHECKING:
    from saleor.plugins.manager import PluginsManager
    from saleor.plugins.sap_orders.plugin import SAPPlugin


class UpsertSAPCreditMemoDocument(ModelMutation):
    """Credit memos and returns work almost exactly the same way, so this class is
    almost identical to the UpsertSAPReturnDocument class. Potentially they could share
    code"""
    credit_memo = graphene.Field(
        SAPCreditMemo,
        description="The credit memo that was upserted."
    )

    class Arguments:
        doc_entry = graphene.Int(
            required=True,
            description="The DocEntry value from SAP (primary key for SAP docs).",
        )

    class Meta:
        description = "Updates or creates returns for an order."
        model = models.SAPCreditMemo
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

        sap_credit_memo = sap_plugin.fetch_credit_memo(data["doc_entry"])

        # Try and figure out which return this goes to which is kept in the
        # BaseEntry field
        order = None
        try:
            return_doc_entry = sap_credit_memo.get("DocumentLines", [])[0]["BaseEntry"]
        except IndexError:
            pass
        else:
            if _return := SAPReturn.objects.filter(
                doc_entry=return_doc_entry
            ).first():
                order = _return.order

        business_partner = models.BusinessPartner.objects.get(
            sap_bp_code=sap_credit_memo["CardCode"]
        )
        if sap_credit_memo["DocCurrency"] == "$":
            # We currently only support USD but conceivably could accept others in the
            # future
            currency = "USD"
        else:
            raise ValidationError(f"Unknown currency: {sap_credit_memo['DocCurrency']}")

        if sap_credit_memo["Submitted"] == "tYES":
            refunded = True
        else:
            refunded = False

        credit_memo, _ = models.SAPCreditMemo.objects.update_or_create(
            business_partner=business_partner,
            doc_entry=sap_credit_memo["DocEntry"],
            defaults={
                "create_date": datetime.strptime(
                    sap_credit_memo.get("DocDate"), "%Y-%m-%d"
                ),
                "order": order,
                "remarks": sap_credit_memo.get("Comments"),
                "purchase_order": sap_credit_memo.get("NumAtCard"),
                "currency": currency,
                "total_net_amount": Decimal(sap_credit_memo["DocTotal"])
                - Decimal(sap_credit_memo["VatSum"]),
                "total_gross_amount": Decimal(sap_credit_memo["DocTotal"]),
                "refunded": refunded,  # TODO Verify this
                "status": sap_credit_memo["DocumentStatus"]  # TODO Verify this
            },
        )

        for line in sap_credit_memo["DocumentLines"]:
            variant = ProductVariant.objects.get(sku=line["ItemCode"])
            models.SAPCreditMemoLine.objects.update_or_create(
                sap_credit_memo=credit_memo,
                product_variant=variant,
                defaults={
                    "quantity": line["Quantity"],
                    "unit_price_amount": Decimal(line["Price"]),
                    "currency": currency,
                },
            )

        return UpsertSAPCreditMemoDocument(credit_memo=credit_memo)
