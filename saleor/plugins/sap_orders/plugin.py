import logging
from datetime import datetime
from hashlib import sha256
from decimal import Decimal
from json import JSONDecodeError
from typing import TYPE_CHECKING, Any, List, Optional

import base64
import pytz
import requests
from django.core.exceptions import ValidationError
from prices import TaxedMoney
from slugify import slugify
from urllib3.exceptions import InsecureRequestWarning

from firstech.SAP import CONFIRMED_ORDERS
from firstech.SAP import models as sap_models
from firstech.SAP.constants import CUSTOM_SAP_SHIPPING_TYPE_NAME
from saleor.checkout.models import Checkout
from saleor.discount import DiscountValueType
from saleor.graphql.SAP.mutations.business_partners import (
    upsert_business_partner,
    upsert_business_partner_addresses,
    upsert_business_partner_contacts,
)
from saleor.graphql.SAP.mutations.orders import validate_order_totals
from saleor.order import FulfillmentStatus
from saleor.plugins.base_plugin import BasePlugin, ConfigurationTypeField
from saleor.plugins.sap_orders import (
    SAPServiceLayerConfiguration,
    get_price_list_cache,
    get_sap_cookies,
    is_truthy,
)

if TYPE_CHECKING:
    from saleor.invoice.models import Invoice
    from saleor.order.models import Order, OrderLine


# Suppress only the single warning from urllib3 needed.
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

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

    @property
    def price_list_cache(self):
        return get_price_list_cache(self.config)

    def service_layer_request(
        self,
        method: str,
        entity: str,
        body: Optional[dict] = None,
        skip_cache: Optional[bool] = False,
    ) -> dict:
        method_func = getattr(requests, method, "get")
        response = method_func(
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
            elif response_json.get("error", {}).get("code") == -10:
                # This will occur when trying to create a business partner that already
                # exists. The method that attempts that will handle this error.
                return response_json
            elif response_json.get("error"):
                raise Exception(
                    f"Received an error from the SAP Service Layer: "
                    f"{response_json['error']}"
                )
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
                address.street_address_2 if address.country.code == "US" else "",
                address.city + " " + address.country_area + " " + address.postal_code,
                address.country.code,
            )
        )

    def get_business_partner_from_order(self, order: "Order"):
        # If the order came from a b2bcheckout, the card code should be in the private
        # metadata.
        if order.private_metadata.get("sap_bp_code"):
            return sap_models.BusinessPartner.objects.get(
                sap_bp_code=order.private_metadata["sap_bp_code"]
            )

        # Otherwise the card code can be inferred from the user the order is for.
        try:
            if order.user_id:
                return sap_models.BusinessPartner.objects.get(
                    sapuserprofiles__user_id=order.user_id
                )
        except sap_models.BusinessPartner.MultipleObjectsReturned:
            raise ValidationError(
                "The customer belongs to more than one business partner. Orders for "
                "this user must be created using the B2BCheckoutCreate mutation."
            )
        except sap_models.BusinessPartner.DoesNotExist:
            # The order could be for a guest/anonymous user, or a logged in user that
            # doesn't belong to a business partner using the normal b2c checkout
            pass

        # Create a new card code based on the email address. Card codes must
        # be unique and <= 15 characters long. Our strategy is to use sha256 to hash the
        # email, then base64 encode to increase the character set to reduce the
        # likelihood of a collision. Unfortunately card codes are not case sensitive,
        # so we are casting everything uppercase.
        email_hash = base64.b64encode(sha256(order.user_email.encode("utf-8")).digest())
        card_code = "B2C-" + email_hash.decode("utf-8").upper()[:11]
        billing_address = order.billing_address
        shipping_address = order.shipping_address
        new_bp = {
            "CardName": billing_address.full_name,
            "CardCode": card_code,
            "CardType": "C",
            "BPAddresses": [
                {
                    "AddressType": "bo_BillTo",
                    "AddressName": billing_address.company_name or
                                   order.billing_address.full_name,
                    "Street": billing_address.street_address_1,
                    "BuildingFloorRoom": billing_address.street_address_2,
                    "City": billing_address.city,
                    "State": billing_address.country_area,
                    "Country": billing_address.country.code,
                    "ZipCode": billing_address.postal_code,
                    "RowNum": 1,
                },
                {
                    "AddressType": "bo_ShipTo",
                    "AddressName": shipping_address.company_name or
                                   order.shipping_address.full_name,
                    "Street": shipping_address.street_address_1,
                    "BuildingFloorRoom": shipping_address.street_address_2,
                    "City": shipping_address.city,
                    "State": shipping_address.country_area,
                    "Country": shipping_address.country.code,
                    "ZipCode": shipping_address.postal_code,
                    "RowNum": 2,
                },
            ],
            "ContactEmployees": [
                {
                    "Name": order.user.name if order.user else order.user_email,
                    "E_Mail": order.user_email,
                    "Phone1": order.billing_address.phone,
                }
            ]
        }
        # Post a new business partner to SAP
        bp: dict = self.service_layer_request(
            "post", "BusinessPartners", body=new_bp
        )
        if bp.get("error", {}).get("code") == -10:
            # A business partner with that card code already exists in SAP.
            bp: dict = self.fetch_business_partner(card_code)
        else:
            self.fill_in_business_partner_details(bp)

        # Perform the usual steps for upserting a business partner from SAP
        business_partner: sap_models.BusinessPartner = upsert_business_partner(bp)
        upsert_business_partner_addresses(bp, business_partner)
        upsert_business_partner_contacts(bp, business_partner)
        return business_partner

    def get_order_for_sap(self, order: "Order"):
        """Build up the json payload needed to post/patch a sales order to SAP"""
        if not (business_partner := self.get_business_partner_from_order(order)):
            return

        try:
            due_date = order.metadata["due_date"]
        except KeyError:
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

        order_for_sap = {
            "CardCode": business_partner.sap_bp_code,
            "DocDate": order.created.strftime("%Y-%m-%d"),
            "DocDueDate": due_date,
            "NumAtCard": order.metadata.get("po_number"),
            "Address": self.address_to_string(order.billing_address),
            "Address2": self.address_to_string(order.shipping_address),
            "PayToCode": order.billing_address.company_name,
            "ShipToCode": order.shipping_address.company_name,
        }
        if order.shipping_method.name != CUSTOM_SAP_SHIPPING_TYPE_NAME:
            order_for_sap["TransportationCode"] = transportation_code

        if order.shipping_price is not None:
            order_for_sap["DocumentAdditionalExpenses"] = [
                {
                    "ExpenseCode": 1,
                    "LineTotal": float(order.shipping_price.net.amount),
                }
            ]

        document_lines = []
        for line_item in order.lines.all():
            document_lines.append(self.prepare_order_line_for_SAP(line_item))

        order_for_sap["DocumentLines"] = document_lines

        # Apply any discounts on the entire order
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
        if order.status not in CONFIRMED_ORDERS:
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
            validate_order_totals(order, result)
            order.store_value_in_private_metadata(
                items={
                    "doc_entry": result["DocEntry"],
                    "sap_bp_code": str(result["CardCode"]),
                }
            )
            order.store_value_in_metadata(items={"due_date": result["DocDueDate"]})
            order.save(update_fields=["metadata", "private_metadata"])

        return previous_value

    def order_confirmed(self, order: "Order", previous_value: Any):
        """Trigger when order is confirmed by staff.

        Overwrite this method if you need to trigger specific logic after an order is
        confirmed.
        """
        return self.order_created(order, previous_value)

    def order_updated(self, order: "Order", previous_value: Any) -> Any:
        """Trigger when order is updated. Also triggered when fulfillments are created
        or edited."""
        # Only send sales orders to SAP once they have been confirmed, or if there is a
        # doc entry already.
        if (
                order.status not in CONFIRMED_ORDERS
                and not order.private_metadata.get("doc_entry")
        ):
            return previous_value

        if doc_entry := order.private_metadata.get("doc_entry"):
            # Update any existing sales order in SAP
            self.service_layer_request(
                "patch", f"Orders({doc_entry})", body=self.get_order_for_sap(order)
            )
            # Unfortunately SAP doesn't return the object after patching, so we need
            # to fetch it in order to validate the order totals.
            validate_order_totals(
                order,
                self.service_layer_request("get", f"Orders({doc_entry})")
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
                        sap_line = self.prepare_order_line_for_SAP(line)
                        sap_line.update(
                            {
                                "DocEntry": doc_entry,
                                "WarehouseCode": line.stock.warehouse.metadata[
                                    "warehouse_id"
                                ],
                            }
                        )
                        document_lines.append(sap_line)

                    response = self.service_layer_request(
                        "post",
                        "DeliveryNotes",
                        body={
                            "DocEntry": doc_entry,
                            "CardCode": order.private_metadata["sap_bp_code"],
                            "TrackingNumber": fulfillment.tracking_number,
                            "DocumentLines": document_lines,
                            "NumAtCard": order.metadata.get("po_number"),
                        },
                    )
                    fulfillment.store_value_in_private_metadata(
                        items={"doc_entry": response["DocEntry"]}
                    )
                    fulfillment.save(update_fields=["private_metadata"])
        else:
            # Try to create a new sales order in SAP since evidently this one isn't
            # attached to an SAP order yet.
            return self.order_created(order, previous_value)

        return previous_value

    def order_cancelled(self, order: "Order", previous_value: Any) -> Any:
        """Trigger when order is cancelled."""
        # Only send sales orders to SAP once they have been confirmed
        if order.status not in CONFIRMED_ORDERS:
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

    @staticmethod
    def clean_email_list(email_text: str) -> List[str]:
        """Given a string of semi-colon, comma, or whitespace separated emails,
        return a list of emails"""
        for separator in (";", " "):
            email_text.replace(separator, ",")

        return [email.strip() for email in email_text.split(",")]

    def fill_in_business_partner_details(self, business_partner: dict):
        """Given a dict of a business partner from SAP. Look up the other related key
        values. Modifies the dict in place"""

        # Look up the name of the payment terms and add it to the dict
        if business_partner.get("PayTermsGrpCode"):
            payment_terms: str = self.service_layer_request(
                "get", f"PaymentTermsTypes({business_partner['PayTermsGrpCode']})"
            ).get("PaymentTermsGroupName")

            business_partner["payment_terms"] = payment_terms
        else:
            business_partner["payment_terms"] = None

        # Look up the channel and add it
        if business_partner.get("PriceListNum"):
            channel_name = self.price_list_cache[business_partner["PriceListNum"]]
            channel_slug = slugify(channel_name)
            business_partner["channel_slug"] = channel_slug
        else:
            business_partner["channel_slug"] = None

        # Get outside sales rep emails and add them
        outside_sales_rep_emails = []
        if business_partner.get("SalesPersonCode"):
            outside_sales_rep: dict = self.service_layer_request(
                "get", f"SalesPersons({business_partner['SalesPersonCode']})"
            )

            # Turn the ; separated string into a list, and only keep email addresses
            # that aren't compustar emails.
            if outside_sales_rep.get("Email"):
                outside_sales_rep_emails = list(
                    filter(
                        lambda email: not email.endswith("@compustar.com"),
                        self.clean_email_list(outside_sales_rep["Email"]),
                    )
                )

            business_partner["outside_sales_rep_emails"] = outside_sales_rep_emails
            business_partner["outside_sales_rep_name"] = outside_sales_rep.get(
                "SalesEmployeeName"
            )

    def fetch_business_partner(self, sap_bp_code: str) -> dict:
        """Used to get a business partner from SAP using the card code. Also looks up
        all the other information we need on business partners from other tables"""
        business_partner: dict = self.service_layer_request(
            "get", f"BusinessPartners('{sap_bp_code}')"
        )
        self.fill_in_business_partner_details(business_partner)
        return business_partner

    def fetch_order(self, doc_entry: int) -> dict:
        return self.service_layer_request("get", f"Orders({doc_entry})")

    def fetch_product(self, sku: str) -> dict:
        sap_product = self.service_layer_request("get", f"Items('{sku}')")

        # insert the price list name into the product's price lists
        for item_price in sap_product.get("ItemPrices", []):
            item_price["PriceListName"] = self.price_list_cache[item_price["PriceList"]]

        return sap_product

    def fetch_shipping_type(self, code: int) -> dict:
        return self.service_layer_request("get", f"ShippingTypes({code})")

    def calculate_order_shipping(
        self, order: "Order", previous_value: TaxedMoney
    ) -> TaxedMoney:
        if order.shipping_method.name == CUSTOM_SAP_SHIPPING_TYPE_NAME:
            # Leave the shipping price alone if the shipping method matches our dummy
            # shipping method. This should only occur if the shipping method and/or
            # shipping price have been manually set in SAP.
            return order.shipping_price

        return previous_value

    @staticmethod
    def prepare_order_line_for_SAP(order_line: "OrderLine") -> dict:
        """Given a Saleor OrderLine, prepare a dict to be upserted to SAP. This can be
        used in an SAP order, delivery document, etc.
        """
        # Without knowing what tax code to apply, these are the only fields we can
        # update in SAP.
        document_line = {
            "ItemCode": order_line.product_sku,
            "Quantity": order_line.quantity,
            "UnitPrice": float(order_line.undiscounted_unit_price_net_amount),
        }
        # Note: SAP only supports "discounts" by percentage. If there is a
        # fixed discount amount in a saleor order, the discount will be
        # reflected in the unit_price_net_amount
        if order_line.unit_discount_type == DiscountValueType.PERCENTAGE:
            document_line["DiscountPercent"] = float(order_line.unit_discount_value)
        else:
            document_line["DiscountPercent"] = 0
            document_line["UnitPrice"] = float(order_line.unit_price_net_amount)

        return document_line
