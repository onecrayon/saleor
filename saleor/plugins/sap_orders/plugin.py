from json import JSONDecodeError
from typing import Any, Optional

import requests
from django.core.exceptions import ValidationError

from firstech.SAP import models as sap_models
from saleor.checkout.models import Checkout
from saleor.discount import DiscountValueType
from saleor.order import FulfillmentStatus, OrderStatus
from saleor.plugins.sap_orders import (
    SAPServiceLayerConfiguration,
    get_sap_cookies,
    is_truthy,
)

from ..base_plugin import BasePlugin, ConfigurationTypeField


class SAPPlugin(BasePlugin):
    """Whenever an order is created or updated, we need to sync those changes to SAP"""

    PLUGIN_ID = "firstech.sap"
    PLUGIN_NAME = "SAP Service Layer Plugin"
    CONFIGURATION_PER_CHANNEL = False

    DEFAULT_CONFIGURATION = [
        {"name": "Username", "value": None},
        {"name": "Password", "value": None},
        {"name": "Database", "value": None},
        {"name": "SAP Service Layer URL", "value": None},
        {"name": "SSL Verification", "value": True},
    ]

    CONFIG_STRUCTURE = {
        "Username": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Provide the username for the SAP Service layer connection",
            "label": "SAP Service Layer username",
        },
        "Password": {
            "type": ConfigurationTypeField.PASSWORD,
            "help_text": "Provide the password for the SAP Service layer connection",
            "label": "SAP Service Layer password",
        },
        "Database": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Provide the name of the SAP database",
            "label": "SAP Service Layer database name",
        },
        "SAP Service Layer URL": {
            "type": ConfigurationTypeField.STRING,
            "help_text": "Provide the URL to the SAP Service Layer",
            "label": "SAP Service Layer URL",
        },
        "SSL Verification": {
            "type": ConfigurationTypeField.BOOLEAN,
            "help_text": "Whether or not SSL should be verified "
            "when communicating with SAP",
            "label": "SSL Verification",
        },
    }

    CONFIRMED_ORDERS = (
        OrderStatus.UNFULFILLED,
        OrderStatus.PARTIALLY_FULFILLED,
        OrderStatus.FULFILLED,
        OrderStatus.PARTIALLY_RETURNED,
        OrderStatus.RETURNED,
        OrderStatus.CANCELED,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Convert to dict to easier take config elements
        configuration = {item["name"]: item["value"] for item in self.configuration}

        self.config = SAPServiceLayerConfiguration(
            username=configuration["Username"],
            password=configuration["Password"],
            database=configuration["Database"],
            url=configuration["SAP Service Layer URL"],
            verify_ssl=is_truthy(configuration["SSL Verification"]),
        )

    def service_layer_request(
        self, method: str, entity: str, body: Optional[dict] = None
    ) -> dict:
        method = getattr(requests, method, "get")
        response = method(
            url=self.config.url + entity,
            json=body,
            cookies=get_sap_cookies(self.config),
            headers={"B1S-ReplaceCollectionsOnPatch": "true"},
            verify=self.config.verify_ssl,
        )
        try:
            return response.json()
        except JSONDecodeError:
            return {}

    @staticmethod
    def address_to_string(address: "Address"):
        """Convert an address object into a string breaking the parts up by carriage
        returns. This is specifically for populating the address fields in an SAP sales
        order.

        Note: Canadian addresses don't have a second line
        """
        return "\r".join(
            (
                address.street_address_1,
                address.street_address_2 if address.country.code == "US" else None,
                address.city + " " + address.country_area + " " + address.postal_code,
                address.country.code,
            )
        )

    def get_order_for_sap(self, order: "Order"):
        """Build up the json payload needed to post/patch a sales order to SAP"""
        try:
            business_partner = sap_models.BusinessPartner.objects.get(
                sapuserprofiles__user_id=order.user_id
            )
        except sap_models.BusinessPartner.MultipleObjectsReturned:
            # TODO:
            # Supposedly it's possible for a user to belong to more than one business
            # partner, but when an order is placed, how do we know which BP the order
            # should go to?
            return
        except sap_models.BusinessPartner.DoesNotExist:
            return

        try:
            due_date = order.metadata.get("due_date").strftime("%Y-%m-%d")
        except AttributeError:
            # Supposedly the due_date is the expected ship date for an order. But SAP
            # doesn't accept posting new orders without one, so default to the order
            # created date since we don't have any other date to go off of
            due_date = order.created.strftime("%Y-%m-%d")

        try:
            transportation_code = order.shipping_method.private_metadata.get(
                "TrnspCode"
            )
        except AttributeError:
            transportation_code = None

        if not (po_number := order.metadata.get("po_number")):
            try:
                checkout = Checkout.objects.get(token=order.checkout_token)
                po_number = checkout.metadata.get("po_number")
            except (ValidationError, Checkout.DoesNotExist):
                # A validation error can be raised if the checkout_token is blank
                po_number = None

        order_for_sap = {
            "CardCode": business_partner.sap_bp_code,
            "DocDate": order.created.strftime("%Y-%m-%d"),
            "DocDueDate": due_date,
            "NumAtCard": po_number,
            "TransportationCode": transportation_code,
            "Address": self.address_to_string(order.billing_address),
            "Address2": self.address_to_string(order.shipping_address),
        }

        document_lines = []
        for line_item in order.lines.all():
            document_line = {
                "ItemCode": line_item.product_sku,
                "Quantity": line_item.quantity,
                # Possibly include pricing/discount information in case of discount
                "UnitPrice": float(line_item.undiscounted_unit_price_gross_amount),
            }
            # Note: SAP only supports "discounts" by percentage. If there is a
            # fixed discount amount in a saleor order, the discount will be
            # reflected in the unit_price_gross_amount
            if line_item.unit_discount_type == DiscountValueType.PERCENTAGE:
                document_line["DiscountPercent"] = float(line_item.unit_discount_value)
            else:
                document_line["DiscountPercent"] = 0
                document_line["UnitPrice"] = float(line_item.unit_price_gross_amount)

            document_lines.append(document_line)

        order_for_sap["DocumentLines"] = document_lines

        if discount := order.discounts.first():
            if discount.value_type == DiscountValueType.PERCENTAGE:
                order_for_sap["DiscountPercent"] = float(discount.value)
            elif discount.value_type == DiscountValueType.FIXED:
                # TODO: WHAT TO DO ABOUT THIS?
                # SAP doesn't support fixed amount discounts on sales orders but we
                # don't need to support that feature, so we need a way to turn off
                # that discount type. Probably easiest to remove it from the dashboard
                # since raising a validation error here doesn't do much besides kill the
                # plugin logic
                pass
        else:
            # This handles situations where a discount could have been removed.
            order_for_sap["DiscountPercent"] = 0

        return order_for_sap

    def order_created(self, order: "Order", previous_value: Any):
        """Trigger when order is created. Is triggered by admins creating an order in
        the dashboard, and also when users complete the checkout process.
        """
        # Only send sales orders to SAP once they have been confirmed
        if order.status not in self.CONFIRMED_ORDERS:
            return previous_value

        if order.private_metadata.get("doc_entry"):
            # When a draft order is "finalized" it triggers the "order_created" method
            # instead of the "order_updated" method
            return self.order_updated(order, previous_value)

        order_data = self.get_order_for_sap(order)
        if not order_data:
            return previous_value

        # Create a new sales order in SAP
        result = self.service_layer_request("post", "Orders", body=order_data)
        # Get the doc_entry from the response and save it in metadata
        if result.get("DocEntry"):
            order.store_value_in_private_metadata(
                items={
                    "doc_entry": str(result["DocEntry"]),
                    "sap_bp_code": str(result["CardCode"]),
                }
            )
            order.save(update_fields=["private_metadata"])

        return previous_value

    def order_confirmed(self, order: "Order", previous_value: Any):
        """Trigger when order is confirmed by staff.

        Overwrite this method if you need to trigger specific logic after an order is
        confirmed.
        """
        return NotImplemented

    def order_updated(self, order: "Order", previous_value: Any) -> Any:
        """Trigger when order is updated. Also triggered when fulfillments are created
        or edited."""
        # Only send sales orders to SAP once they have been confirmed
        if order.status not in self.CONFIRMED_ORDERS:
            return previous_value

        if doc_entry := order.private_metadata.get("doc_entry"):
            # Update and existing sales order in SAP
            self.service_layer_request(
                "patch", f"Orders({doc_entry})", body=self.get_order_for_sap(order)
            )

            # Update Delivery Documents
            fulfillments = order.fulfillments.all()
            for fulfillment in fulfillments:
                if delivery_doc_entry := fulfillment.private_metadata.get("doc_entry"):
                    # The only thing we can or need to update is tracking number
                    if fulfillment.status == FulfillmentStatus.CANCELED:
                        # TODO Cant actually cancel these??
                        # self.service_layer_request(
                        #     "post",
                        #     f"DeliveryNotes({delivery_doc_entry})/Cancel",
                        # )
                        pass
                    else:
                        self.service_layer_request(
                            "patch",
                            f"DeliveryNotes({delivery_doc_entry})",
                            body={"TrackingNumber": fulfillment.tracking_number},
                        )
                else:
                    lines = fulfillment.lines.all()
                    document_lines = []
                    for line in lines:
                        document_lines.append(
                            {
                                "ItemCode": line.order_line.variant.sku,
                                "Quantity": line.quantity,
                            }
                        )

                    response = self.service_layer_request(
                        "post",
                        "DeliveryNotes",
                        body={
                            "CardCode": order.private_metadata["sap_bp_code"],
                            "TrackingNumber": fulfillment.tracking_number,
                            "DocumentLines": document_lines,
                        },
                    )
                    fulfillment.store_value_in_private_metadata(
                        items={"doc_entry": str(response["DocEntry"])}
                    )
                    fulfillment.save(update_fields=["private_metadata"])
        else:
            # Try to create a new sales order in SAP since evidently this one isn't
            # attached to an SAP order yet.
            self.order_created(order, previous_value)

        return previous_value

    def order_cancelled(self, order: "Order", previous_value: Any) -> Any:
        """Trigger when order is cancelled."""
        # Only send sales orders to SAP once they have been confirmed
        if order.status not in self.CONFIRMED_ORDERS:
            return previous_value

        if doc_entry := order.private_metadata.get("doc_entry"):
            self.service_layer_request(
                "post",
                f"Orders({doc_entry})/Cancel",
                body=self.get_order_for_sap(order),
            )

        return previous_value

    def order_fulfilled(self, order: "Order", previous_value: Any) -> Any:
        """Trigger when order is fulfilled."""
        return NotImplemented

    def fetch_delivery_document(self, doc_entry: str) -> dict:
        return self.service_layer_request("get", f"DeliveryNotes({doc_entry})")
