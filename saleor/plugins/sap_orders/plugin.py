import logging
from datetime import datetime
from json import JSONDecodeError
from slugify import slugify
from typing import TYPE_CHECKING, Any, Optional

import pytz
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

if TYPE_CHECKING:
    from saleor.invoice.models import Invoice
    from saleor.order.models import Order


logger = logging.getLogger(__name__)


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
        self,
        method: str,
        entity: str,
        body: Optional[dict] = None,
        skip_cache: Optional[bool] = False,
    ) -> dict:
        method = getattr(requests, method, "get")
        response = method(
            url=self.config.url + entity,
            json=body,
            cookies=get_sap_cookies(self.config, skip_cache=skip_cache),
            headers={"B1S-ReplaceCollectionsOnPatch": "true"},
            verify=self.config.verify_ssl,
        )
        try:
            response_json = response.json()
            if response_json.get("error", {}).get("code") == 301 and not skip_cache:
                # only try again if skip_cache was initially false so that we don't get
                # stuck in a loop
                return self.service_layer_request(method, entity, body, skip_cache=True)
            return response_json
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

    @staticmethod
    def get_business_partner_from_order(order: "Order"):
        try:
            return sap_models.BusinessPartner.objects.get(
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

    @classmethod
    def get_order_for_sap(cls, order: "Order"):
        """Build up the json payload needed to post/patch a sales order to SAP"""
        if not (business_partner := cls.get_business_partner_from_order(order)):
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
            "Address": cls.address_to_string(order.billing_address),
            "Address2": cls.address_to_string(order.shipping_address),
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
                    "doc_entry": result["DocEntry"],
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
                                "WarehouseCode": line.stock.warehouse.metadata[
                                    "warehouse_code"
                                ],
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
                        items={"doc_entry": response["DocEntry"]}
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

    def fetch_delivery_document(self, doc_entry: int) -> dict:
        return self.service_layer_request("get", f"DeliveryNotes({doc_entry})")

    @classmethod
    def generate_saleor_invoice(
        cls, invoice: "Invoice", down_payment: Optional[float] = None
    ) -> dict:
        """Generates a dict containing all the information necessary for an invoice.
        This dict can be saved as a JSON object or used to fill an HTML template, etc.

        :param invoice: This object should already have been posted to SAP so
            that it contains certain values that SAP generates for an invoice such as
            the invoice number (doc_entry).
        :param down_payment: Optionally provide a down payment amount from an SAP
            invoice document.
        """
        now = datetime.now(tz=pytz.utc)
        order = invoice.order
        if not (business_partner := cls.get_business_partner_from_order(order)):
            return

        # Summarize the line items on this order
        line_items = []
        for line_item in order.lines.all():
            # Gather all of the fulfillments so far on this line item
            quantity_fulfilled = 0
            fulfilled_items = []
            for fulfillment_line in line_item.fulfillment_lines.all():
                quantity_fulfilled += fulfillment_line.quantity
                fulfillment = fulfillment_line.fulfillment
                fulfilled_items.append(
                    {
                        "qty": fulfillment_line.quantity,
                        "tracking_number": fulfillment.tracking_number,
                        "ship_date": fulfillment.created,
                        "shipped_from": fulfillment_line.stock.warehouse.name,
                        "shipped_to": order.shipping_address.as_data(),
                    }
                )

            line_items.append(
                {
                    "line_total": line_item.total_price_net,
                    "name": line_item.product_name,
                    "sku": line_item.variant.sku,
                    "price": line_item.unit_price_net,
                    "quantity_fulfilled": quantity_fulfilled,
                    "quantity_ordered": line_item.quantity,
                    "quantity_unfulfilled": line_item.quantity - quantity_fulfilled,
                    "deliveries": fulfilled_items,
                }
            )

        # Summarize all of the payments so far for this order
        payments = []
        for payment in order.payments.all():
            percentage_paid = 100 * round(
                payment.captured_amount / order.total_gross_amount, 2
            )
            payments.append(
                {
                    "payment_date": payment.created,
                    "percentage_paid": percentage_paid,
                    "total": payment.captured_amount,
                }
            )

        invoice = {
            "invoice_number": invoice.number,
            "billing_address": order.billing_address.as_data(),
            "company_name": business_partner.company_name,
            "create_date": now,
            "outside_sales_rep": business_partner.outside_sales_rep,
            "payment_due_date": None,  # TODO
            "po_number": order.metadata.get("po_number"),
            "remarks": order.metadata.get("remarks"),
            "sap_bp_code": business_partner.sap_bp_code,
            "shipping_preference": order.shipping_method_name,
            "status": order.status,
            "sub_total": order.get_subtotal().net,
            "tax": order.total.tax,
            "total": order.total_gross,
            "down_payment": down_payment,
            "early_pay_discount": None,  # TODO
            "amount_paid": order.total_paid,
            "total_amount_due": order.total_gross - order.total_paid,
            "items": line_items,
            "payments": payments,
        }

        return invoice

    def fetch_invoice(self, doc_entry: int) -> dict:
        """Used to get an invoice from SAP when we know the Doc Entry"""
        return self.service_layer_request("get", f"Invoices({doc_entry})")

    def invoice_request(
        self,
        order: "Order",
        invoice: "Invoice",
        number: Optional[str],
        previous_value: Any,
    ) -> Any:
        """Trigger when invoice creation starts.

        Invoices are only created in SAP, then synced to saleor. Never the other way
        around. This is because we do not have the appropriate product license in SAP
        to create invoices. They are instead created in batches daily.
        """

        return NotImplemented

    def fetch_return(self, doc_entry: int) -> dict:
        """Used to get a return document from SAP from the doc_entry"""
        return self.service_layer_request("get", f"Returns({doc_entry})")

    def fetch_credit_memo(self, doc_entry: int) -> dict:
        """Used to get a credit memo document from SAP from the doc_entry"""
        return self.service_layer_request("get", f"CreditNotes({doc_entry})")

    def fetch_business_partner(self, sap_bp_code: str) -> dict:
        """Used to get a business partner from SAP using the card code. Also looks up
        all the other information we need on business partners from other tables"""
        business_partner: dict = self.service_layer_request(
            "get", f"BusinessPartners('{sap_bp_code}')"
        )

        # Look up the name of the payment terms and add it to the dict
        if business_partner['PayTermsGrpCode']:
            payment_terms: str = self.service_layer_request(
                "get", f"PaymentTermsTypes({business_partner['PayTermsGrpCode']})"
            ).get("PaymentTermsGroupName")

            business_partner["payment_terms"] = payment_terms
        else:
            business_partner["payment_terms"] = None

        # Look up the channel and add it
        if business_partner['PriceListNum']:
            channel_name: str = self.service_layer_request(
                "get", f"PriceLists({business_partner['PriceListNum']})"
            ).get("PriceListName")

            channel_slug = slugify(channel_name)
            business_partner["channel_slug"] = channel_slug
        else:
            business_partner["channel_slug"] = None

        # Get outside sales rep emails and add them
        outside_sales_rep_emails = []
        if business_partner['SalesPersonCode']:
            outside_sales_rep: dict = self.service_layer_request(
                "get", f"SalesPersons({business_partner['SalesPersonCode']})"
            )

            # Turn the ; separated string into a list, and only keep email addresses
            # that aren't compustar emails.
            if outside_sales_rep.get("Email"):
                outside_sales_rep_emails = list(
                    filter(
                        lambda email: not email.endswith("@compustar.com"),
                        outside_sales_rep["Email"].split(";"),
                    )
                )

            business_partner["outside_sales_rep_emails"] = outside_sales_rep_emails
            business_partner["outside_sales_rep_name"] = outside_sales_rep.get(
                "SalesEmployeeName"
            )

        return business_partner

    def fetch_order(self, doc_entry: int) -> dict:
        return self.service_layer_request("get", f"Orders({doc_entry})")

    def fetch_product(self, sku: str) -> dict:
        sap_product = self.service_layer_request("get", f"Items('{sku}')")

        # Get all of the price lists names / slugs
        # the code and name are unlikely to change, so it seems very unnecessary to look
        # this up every time. Maybe save this in the database somewhere?
        skip = 0
        price_list_cache = {}
        while skip is not None:
            price_lists = self.service_layer_request("get", f"PriceLists?$skip={skip}")
            for price_list in price_lists["value"]:
                price_list_cache[price_list["PriceListNo"]] = price_list[
                    "PriceListName"
                ]

            if "odata.nextLink" in price_lists:
                skip += 20
            else:
                skip = None

        # insert the price list name into the product's price lists
        for item_price in sap_product.get("ItemPrices", []):
            item_price["PriceListName"] = price_list_cache[item_price["PriceList"]]

        return sap_product
