from decimal import Decimal
from typing import TYPE_CHECKING, List, Tuple

import graphene
from django.core.exceptions import ValidationError

import saleor.product.models as product_models
from saleor.account import models as user_models
from saleor.core.permissions import OrderPermissions
from saleor.discount import DiscountValueType
from saleor.discount import models as discount_models
from saleor.graphql.core.types.common import OrderError
from saleor.graphql.order.mutations.discount_order import (
    OrderDiscountAdd,
    OrderDiscountUpdate,
    OrderLineDiscountUpdate,
)
from saleor.graphql.order.mutations.draft_orders import (
    DraftOrderComplete,
    DraftOrderInput,
    DraftOrderUpdate,
)
from saleor.graphql.order.mutations.orders import (
    OrderLineDelete,
    OrderLinesCreate,
    OrderLineUpdate,
)
from saleor.order import models as order_models
from saleor.order.utils import get_valid_shipping_methods_for_order

from ....core.tracing import traced_atomic_transaction

if TYPE_CHECKING:
    from saleor.plugins.manager import PluginsManager
    from saleor.plugins.sap_orders.plugin import SAPPlugin


class SAPLineItemInput(graphene.InputObjectType):
    sku = graphene.String()
    quantity = graphene.Int()


class SAPOrderMetadataInput(graphene.InputObjectType):
    due_date = graphene.String(
        description="Expected shipping date. From ORDR.DocDueDate"
    )
    date_shipped = graphene.String(description="From ORDR.ShipDate")
    payment_method = graphene.String(description="From ORDR.PaymentMethod")
    PO_number = graphene.String(description="From ORDR.ImportFileNum")


class SAPOrderInput(graphene.InputObjectType):
    draft_order_input = DraftOrderInput(
        required=True, description="Fields required to create an order."
    )
    lines = graphene.List(
        of_type=SAPLineItemInput, description="List of order line items"
    )
    metadata = graphene.Field(
        SAPOrderMetadataInput,
        description="Additional SAP information can be stored as metadata.",
    )


class UpsertSAPOrder(DraftOrderUpdate):
    """For syncing sales orders in SAP to orders in Saleor. See the docstring in the
    methods below for details on the billing and shipping address inputs.
    """

    class Arguments:
        doc_entry = graphene.Int(
            required=True,
            description="The DocEntry value from SAP (primary key for SAP orders).",
        )
        confirm_order = graphene.Boolean(
            required=False,
            default_value=False,
            description="Whether or not to attempt to confirm this order automatically.",
        )

    class Meta:
        description = "Creates or updates a draft order."
        model = order_models.Order
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def get_instance(cls, info, **data):
        instance = (
            order_models.Order.objects.filter(
                private_metadata__doc_entry=data["doc_entry"],
            )
            .prefetch_related("lines")
            .first()
        )

        if not instance:
            instance = cls._meta.model()

        return instance

    @staticmethod
    def parse_address_etc(city_state_zip: str, country: str) -> Tuple[str, str, str]:
        """This function takes part of an address line that has the city, state and zip
        in it and splits them up into those pieces. Assumes that the last word is the
        zip, the next to last word is the state abbreviation, and the remaining words
        are the city.

        The country is also needed as an input because canadian postal codes are two
        words.

        Example:
        "Lake Forest Park WA 98765" -> "Lake Forest Park", "WA", "98765"
        """
        words = city_state_zip.split()
        postal_code = words.pop()

        # Canadian postal codes are two words
        if country == "CA":
            postal_code = words.pop() + " " + postal_code

        state = words.pop()
        city = " ".join(words)
        return city, state, postal_code

    @staticmethod
    def parse_country(country: str) -> str:
        # Most likely the country will come from SAP as either "USA" or "Canada",
        # but it's possible for an SAP user to manually enter an address so I'm being
        # as forgiving as possible with spellings
        if country.upper() in (
            "USA",
            "US",
            "UNITED STATES",
            "UNITED STATES OF AMERICA",
        ):
            return "US"
        elif country.upper() in ("CANADA", "CA"):
            return "CA"
        else:
            raise ValidationError("Country not recognized")

    @classmethod
    def parse_address_string(cls, address_string):
        """We're pulling billing and shipping addresses from the SAP Order's Address
        and Address2 fields, respectively. These fields normalize the address into a
        single text field where different address elements are separated by \r. This
        function parses those out into a dict.

        Example inputs for US address:
            123 Fake St.\rUnit A\rTownsville NY 12345\rUSA
            742 Evergreen Terrace\r\rSpringfield OR 98123\rUSA

        Example input for CA address:
            3213 Curling Lane Apt. C\rVancouver BC V1E 4X3\rCANADA
        """
        address_lines: List = address_string.split("\r")
        # The last line is always the country
        country = cls.parse_country(address_lines.pop())

        # The next to last line contains the city, state (or province), and postal code
        city, state, postal_code = cls.parse_address_etc(address_lines.pop(), country)

        # The remaining 1 or 2 lines (US addresses should have 2 lines, CA should only
        # have 1)
        line_1 = address_lines[0]

        # In the event we have more than 2 extra address lines, we'll just concatenate
        # them into one big line
        if len(address_lines) >= 2:
            line_2 = " ".join(address_lines[1:])
        else:
            line_2 = None

        return {
            "street_address_1": line_1,
            "street_address_2": line_2,
            "city": city,
            "country_area": state,
            "country": country,
            "postal_code": postal_code,
        }

    @classmethod
    @traced_atomic_transaction()
    def perform_mutation(cls, _root, info, **data):
        manager: PluginsManager = info.context.plugins
        sap_plugin: SAPPlugin = manager.get_plugin(plugin_id="firstech.sap")
        if not sap_plugin:
            # the SAP plugin is inactive or doesn't exist
            return

        # Get the order instance
        order: order_models.Order = cls.get_instance(info, **data)
        new_order = False if order.pk else True
        sap_order = sap_plugin.fetch_order(data["doc_entry"])
        bp = sap_plugin.fetch_business_partner(sap_order["CardCode"])
        billing_address = cls.parse_address_string(sap_order["Address"])
        shipping_address = cls.parse_address_string(sap_order["Address2"])
        contact_list: List[dict] = bp["ContactEmployees"]

        # Figure out which user should be attached to this Order
        for contact in contact_list:
            if contact["InternalCode"] == sap_order["ContactPersonCode"]:
                normalized_email = user_models.UserManager.normalize_email(
                    contact["E_Mail"]
                )
                user = user_models.User.objects.get(email=normalized_email)
                break
        else:
            user = None

        channel_id = product_models.Channel.objects.values_list("id", flat=True).get(
            slug=bp["channel_slug"]
        )

        draft_order_input = {
            "billing_address": billing_address,
            "user": graphene.Node.to_global_id("User", user.id) if user else None,
            "user_email": user.email if user else None,
            "shipping_address": shipping_address,
            "channel_id": graphene.Node.to_global_id("Channel", channel_id),
        }

        # The SAP order has all the line items, but we need to rename the keys that it
        # uses to match what Saleor's Order mutations expect. We also only care about
        # sku and quantity and not any of the other dozens of fields SAP has.
        lines = []
        # We will make a note of any discounts on line items for later on
        line_item_discounts = {}
        shipping_method_code = None
        document_lines = sap_order.get("DocumentLines", [])
        if document_lines:
            shipping_method_code = document_lines[0].get("ShippingMethod")
            for document_line in document_lines:
                lines.append(
                    {
                        "sku": document_line["ItemCode"],
                        "quantity": int(document_line["Quantity"]),
                        "discount_percent": document_line["DiscountPercent"],
                    }
                )

        # Form the line items for the order
        if lines:
            # We need to translate SKU into variant ids.
            # Sort our line items by SKU
            lines = sorted(lines, key=lambda line: line["sku"])

            # Get all the product variants for the SKUs provided (also sorted by SKU)
            product_variants: List[dict] = list(
                product_models.ProductVariant.objects.filter(
                    sku__in=[line["sku"] for line in lines]
                )
                .values("id", "sku")
                .order_by("sku")
            )

            # Replace each line item's SKU key-value pair with variant's global id
            # There is a possibility that there are SKUs from SAP that don't exist in
            # Saleor, so we will raise a validation error if any exist
            i = 0
            bad_line_items = []
            num_product_variants = len(product_variants)
            for sap_line in lines:
                if (
                    i < num_product_variants
                    and sap_line["sku"] == product_variants[i]["sku"]
                ):
                    sap_line["variant_id"] = graphene.Node.to_global_id(
                        "ProductVariant", product_variants[i]["id"]
                    )
                    line_item_discounts[sap_line["sku"]] = sap_line["discount_percent"]
                    del sap_line["sku"]
                    del sap_line["discount_percent"]
                    i += 1
                else:
                    bad_line_items.append(sap_line["sku"])

            if bad_line_items:
                raise ValidationError(
                    f"The following SKUs do not exist in Saleor: {bad_line_items}"
                )

        metadata = {
            "due_date": sap_order["DocDueDate"] or "",
            "payment_method": sap_order["PaymentMethod"] or "",
            "po_number": sap_order["NumAtCard"] or "",
        }
        # Keep SAP's DocEntry field and business partner code in the private meta data
        # so we can refer to this order again
        private_metadata = {
            "doc_entry": data["doc_entry"],
            "sap_bp_code": sap_order["CardCode"],
        }

        # If this is a new order then we can use the draftOrderCreate mutation which
        # takes the lines argument. Otherwise for an update we can't include lines
        if new_order:
            draft_order_input["lines"] = lines
        else:
            # Channel id can't be changed
            del draft_order_input["channel_id"]

        # Update the draft Order
        # Ok...so. We can't use cls.clean_input for this because we would need to be
        # able to pass in the `input_cls` argument to make sure the
        # BaseMutation.clean_input method is referring to the right input class.
        # (We want to clean theDraftOrderCreateInput not the SAPOrderInput).
        # But the DraftOrderUpdate class doesn't pass the `input_cls` argument through
        # to the BaseMutation class. So we either need to edit the stock saleor code to
        # pass that argument through OR explicitly call a fresh DraftOrderUpdate class
        # to make sure the right input class gets used.
        cleaned_input = DraftOrderUpdate.clean_input(info, order, draft_order_input)
        order = cls.construct_instance(order, cleaned_input)
        cls.clean_instance(info, order)
        cls.save(info, order, cleaned_input)
        cls._save_m2m(info, order, cleaned_input)
        cls.post_save_action(info, order, cleaned_input)

        # Attach our metadata
        order.store_value_in_metadata(items=metadata)
        order.store_value_in_private_metadata(items=private_metadata)
        order.save(update_fields=["metadata", "private_metadata"])

        # For existing orders we must update any changes to line items that were made
        if not new_order:
            existing_lines = order_models.OrderLine.objects.filter(
                order_id=order.id
            ).all()
            line_cache = {}
            for line in existing_lines:
                line_cache[
                    graphene.Node.to_global_id("ProductVariant", line.variant_id)
                ] = line

            lines_to_create = []
            for line in lines:
                if existing_line := line_cache.pop(line["variant_id"], None):
                    if existing_line.quantity != line["quantity"]:
                        # We need to update the qty. There's a bunch of special behind
                        # the scenes actions that take place in the normal update order
                        # mutation. Instead of trying to recreate that all we'll just
                        # call that mutation from here.
                        OrderLineUpdate.perform_mutation(
                            _root,
                            info,
                            id=graphene.Node.to_global_id(
                                "OrderLine", existing_line.id
                            ),
                            input={"quantity": line["quantity"]},
                        )
                else:
                    lines_to_create.append(line)

            # Create the new lines using the mutation for that
            OrderLinesCreate.perform_mutation(
                _root,
                info,
                id=graphene.Node.to_global_id("Order", order.id),
                input=lines_to_create,
            )

            # Delete any remaining lines that weren't updated or added
            for variant_id, line in line_cache.items():
                OrderLineDelete.perform_mutation(
                    _root, info, id=graphene.Node.to_global_id("OrderLine", line.id)
                )

        # Lookup the shipping method by code and update the order
        if shipping_method_code:
            available_shipping_methods = get_valid_shipping_methods_for_order(order)
            shipping_method = available_shipping_methods.filter(
                private_metadata__TrnspCode=str(shipping_method_code)
            ).first()
            order.shipping_method = shipping_method
            order.shipping_method_name = shipping_method.name
            order.save()

        # Include line item discounts
        for line in order.lines.all():
            discount = line_item_discounts[line.product_sku]
            if discount > 0:
                OrderLineDiscountUpdate.perform_mutation(
                    _root,
                    info,
                    input={
                        "value_type": DiscountValueType.PERCENTAGE,
                        "value": Decimal(discount),
                        "reason": "From SAP Order",
                    },
                    order_line_id=graphene.Node.to_global_id("OrderLine", line.id),
                )

        # Include any discounts on the entire sales order
        if sap_order["TotalDiscount"]:
            discount_input = {
                "value_type": DiscountValueType.FIXED,
                "value": Decimal(sap_order["TotalDiscount"]),
                "reason": "From SAP Order",
            }
            try:
                existing_discount_id = (
                    discount_models.OrderDiscount.objects.values_list(
                        "id", flat=True
                    ).get(order_id=order.id)
                )
            except discount_models.OrderDiscount.DoesNotExist:
                OrderDiscountAdd.perform_mutation(
                    _root,
                    info,
                    order_id=graphene.Node.to_global_id("Order", order.id),
                    input=discount_input,
                )
            else:
                OrderDiscountUpdate.perform_mutation(
                    _root,
                    info,
                    discount_id=graphene.Node.to_global_id(
                        "OrderDiscount", existing_discount_id
                    ),
                    input=discount_input,
                )

        # Sanity check to make sure all of the discounts / tax have been copied over
        # correctly.
        if order.total.net.amount != Decimal(sap_order["DocTotal"]):
            raise ValidationError("Saleor order total does not match SAP order total")

        if data.get("confirm_order", False):
            # Try to move this draft order to confirmed
            try:
                DraftOrderComplete.perform_mutation(
                    _root, info, graphene.Node.to_global_id("Order", order.id)
                )
            except ValidationError:
                # If there is not enough stock available for the order, confirmation
                # will fail.
                pass

        return cls.success_response(order)
