import graphene
from typing import TYPE_CHECKING

from saleor.core import JobStatus
from saleor.core.permissions import OrderPermissions
from saleor.graphql.core.mutations import BaseMutation
from saleor.graphql.core.types.common import OrderError
from saleor.graphql.invoice.types import Invoice
from saleor.invoice.models import Invoice as InvoiceModel
from saleor.order.models import Fulfillment as FulfillmentModel

if TYPE_CHECKING:
    from saleor.plugins.manager import PluginsManager
    from saleor.plugins.sap_orders.plugin import SAPPlugin


class UpsertSAPInvoiceDocument(BaseMutation):
    invoice = graphene.Field(Invoice, description="The created invoice.")

    class Arguments:
        doc_entry = graphene.Float(
            required=True,
            description="The DocEntry value from SAP (primary key for SAP docs).",
        )

    class Meta:
        description = "Updates or creates invoices for an order."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        manager: PluginsManager = info.context.plugins
        sap_plugin: SAPPlugin = manager.get_plugin(plugin_id="firstech.sap")
        if not sap_plugin:
            # the SAP plugin is inactive or doesn't exist
            return

        sap_invoice = sap_plugin.fetch_invoice(data["doc_entry"])

        # Need to figure out which order this goes to which can be done by finding a
        # fulfillment with the DocEntry that matches the "BaseEntry" of the lines on the
        # SAP invoice.
        order = FulfillmentModel.objects.filter(
            private_metadata__doc_entry=sap_invoice["DocumentLines"][0]["BaseEntry"]
        ).first().order

        # Initialize the Saleor invoice
        invoice = InvoiceModel(order=order, number=data["doc_entry"])

        # Generate the bulk of the info for our saleor invoice
        invoice.invoice_json = sap_plugin.generate_saleor_invoice(invoice)

        # We aren't actually processing this as a "job" but need to set this or else
        # it will default to "pending"
        invoice.status = JobStatus.SUCCESS
        invoice.save()

        return UpsertSAPInvoiceDocument(invoice=invoice)


