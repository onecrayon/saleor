import graphene
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from saleor.core.permissions import OrderPermissions
from saleor.graphql.core.mutations import BaseMutation
from saleor.graphql.core.types.common import OrderError
from saleor.graphql.order.mutations.fulfillments import (
    OrderFulfill,
    FulfillmentUpdateTracking,
)
from saleor.graphql.order.types import Fulfillment
from saleor.graphql.order.types import Order as OrderType
from saleor.order.models import Order
from saleor.order.models import Fulfillment as FulfillmentModel
from saleor.warehouse.models import Warehouse

if TYPE_CHECKING:
    from saleor.plugins.manager import PluginsManager
    from saleor.plugins.sap_orders.plugin import SAPPlugin


class UpsertSAPDeliveryDocument(BaseMutation):
    """For syncing SAP Delivery documents into Saleor Fulfillments.

    This mutation works a little different from the other ones so far. We are now
    using the SAP service layer. This means that instead of having the integration
    framework send a fully formed mutation with all the details in it, the integration
    framework will simply provide the document id (doc_entry). Then this mutation will
    make an http GET request to the service layer to fetch all the info it needs about
    the delivery document.

    SAP delivery documents are largely immutable once they are created. Similarly to
    Saleor's fulfillment objects, the only thin that can be changed after creation is
    the tracking number.
    """

    fulfillments = graphene.List(
        Fulfillment, description="List of created fulfillments."
    )
    order = graphene.Field(OrderType, description="Fulfilled order.")

    class Arguments:
        doc_entry = graphene.Int(
            required=True,
            description="The DocEntry value from SAP (primary key for SAP docs).",
        )

    class Meta:
        description = "Updates or creates fulfillments for an order."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def update_tracking_number(cls, _root, info, fulfillment, tracking_number):
        FulfillmentUpdateTracking.perform_mutation(
            _root,
            info,
            id=graphene.Node.to_global_id("Fulfillment", fulfillment.id),
            input={"tracking_number": tracking_number},
        )

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        manager: PluginsManager = info.context.plugins
        sap_plugin: SAPPlugin = manager.get_plugin(plugin_id="firstech.sap")
        if not sap_plugin:
            # the SAP plugin is inactive or doesn't exist
            return

        delivery_document = sap_plugin.fetch_delivery_document(data["doc_entry"])

        # See if we already have this delivery doc
        existing_fulfillments = list(
            FulfillmentModel.objects.filter(
                private_metadata__doc_entry=data["doc_entry"]
            )
        )
        if existing_fulfillments:
            for fulfillment in existing_fulfillments:
                # we only need to update the tracking number
                cls.update_tracking_number(
                    _root, info, fulfillment, delivery_document["TrackingNumber"]
                )

            return OrderFulfill(
                fulfillments=existing_fulfillments, order=fulfillment.order
            )

        # We didn't find any existing fulfillments with the doc_entry number so we will
        # attempt to create a new one
        sap_lines = delivery_document["DocumentLines"]
        sales_order_doc_entry = sap_lines[0]["BaseEntry"]
        try:
            order = Order.objects.get(private_metadata__doc_entry=sales_order_doc_entry)
        except (Order.DoesNotExist, Order.MultipleObjectsReturned) as e:
            raise ValidationError(e)

        # Prepare the line items for the fulfillment
        fulfillment_lines = []
        order_lines = order.lines.all()
        for sap_line in sap_lines:
            try:
                warehouse_id = Warehouse.objects.get(
                    metadata__warehouse_id=sap_line["WarehouseCode"]
                ).id
            except (Warehouse.DoesNotExist, Warehouse.MultipleObjectsReturned) as e:
                raise ValidationError(e)

            warehouse_id = graphene.Node.to_global_id("Warehouse", warehouse_id)
            # The SAP delivery document's line items should be in the same order as the
            # SAP and Saleor sales orders, but we will verify that the SKU matches
            for order_line in order_lines:
                if order_line.variant.sku == sap_line["ItemCode"]:
                    order_fulfillment_line_input = {
                        "order_line_id": graphene.Node.to_global_id(
                            "OrderLine", order_line.id
                        ),
                        "stocks": [
                            {
                                "quantity": sap_line["Quantity"],
                                "warehouse": warehouse_id,
                            }
                        ],
                    }
                    fulfillment_lines.append(order_fulfillment_line_input)
                    break
            else:
                raise ValidationError(
                    "There is an SKU in the delivery document that doesn't exist in "
                    "the Saleor sales order. That's bad."
                )

        # This creates one fulfillment per warehouse used
        fulfillments = OrderFulfill.perform_mutation(
            _root,
            info,
            graphene.Node.to_global_id("Order", order.id),
            input={"lines": fulfillment_lines, "notify_customer": True},
        ).fulfillments

        for fulfillment in fulfillments:
            cls.update_tracking_number(
                _root, info, fulfillment, delivery_document["TrackingNumber"]
            )
            fulfillment.store_value_in_private_metadata(
                items={"doc_entry": data["doc_entry"]}
            )
            fulfillment.save(update_fields=["private_metadata"])

        return OrderFulfill(fulfillments=list(order.fulfillments.all()), order=order)
