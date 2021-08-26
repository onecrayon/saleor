from typing import List, Tuple

import graphene
from django.core.exceptions import ValidationError
from django.utils.text import slugify

import saleor.product.models as product_models
from saleor.core.permissions import OrderPermissions
from saleor.graphql.core.types.common import OrderError
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
        input = SAPOrderInput(
            required=True,
            description="Input data for upserting a draft order from SAP.",
        )
        doc_entry = graphene.Int(
            required=True,
            description="The DocEntry value from SAP (primary key for SAP orders).",
        )
        sap_bp_code = graphene.String(
            required=True, description="The SAP CardCode for the order."
        )
        confirm_order = graphene.Boolean(
            required=False,
            default_value=False,
            description="Whether or not to attempt to confirm this order automatically.",
        )
        shipping_method_name = graphene.String(
            description="Name of the shipping method to use."
        )
        channel_name = graphene.String(description="Name of the channel to use.")
        shipping_address = graphene.String(description="Semicolon delimited address.")
        billing_address = graphene.String(description="Semicolon delimited address.")

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
                metadata__doc_entry=data["doc_entry"],
                metadata__sap_bp_code=data["sap_bp_code"],
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
        zip, the next to last word is the state abbreviation, and the remaining words.

        The country is also needed as an input because canadian postal codes are two
        words.

        are the city. Example:
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
        """<rant> Because of what can happen on the SAP side, getting the shipping and
        billing addresses from a sales order is a real mess. Ideally the integration
        framework would be able to include the billing/shipping addresses inside the
        DraftOrderInput type. However, when we pull the address from the database it's
        normalized and we have to parse out street1, street2, city, state, zip, country
        manually. We can do a little bit of that on the SQL side by replacing linebreaks
        with a `;`. Unfortunately the city, state, and zip code are all on one line. And
        then there's no good way to break those pieces up inside the integration
        framework because we can't figure out how to get the javascript plug-in working,
        and God only knows how to do that with xslt/xpath. And of course there are some
        subtle differences in how US and Canadian addresses work. So instead we send it
        over as a string, then we do the rest of the address parsing here in python
        land, and then finally stuff everything back into the DraftOrderInput.</rant>

        Example inputs for US address:
            123 Fake St.;Unit A;Townsville NY 12345;USA
            742 Evergreen Terrace;;Springfield OR 98123;USA

        Example input for CA address:
            3213 Curling Lane Apt. C;Vancouver BC V1E 4X3;CANADA
        """
        address_lines: List = address_string.split(";")
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
    def perform_mutation(cls, _root, info, **data):
        # Get the order instance
        order: order_models.Order = cls.get_instance(info, **data)
        new_order = False if order.pk else True
        input: dict = data["input"]
        draft_order_input = input["draft_order_input"]
        channel_name = data.get("channel_name")
        shipping_method_name = data.get("shipping_method_name")

        if shipping_address := data.get("shipping_address"):
            draft_order_input["shipping_address"] = cls.parse_address_string(
                shipping_address
            )

        if billing_address := data.get("billing_address"):
            draft_order_input["billing_address"] = cls.parse_address_string(
                billing_address
            )

        # Get the channel model object from the channel name
        if channel_name:
            channel = product_models.Channel.objects.get(slug=slugify(channel_name))
            draft_order_input["channel_id"] = graphene.Node.to_global_id(
                "Channel", channel.id
            )

        # Form the line items for the order
        if lines := input.get("lines", []):
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
                    del sap_line["sku"]
                    i += 1
                else:
                    bad_line_items.append(sap_line["sku"])

            if bad_line_items:
                raise ValidationError(
                    f"The following SKUs do not exist in Saleor: {bad_line_items}"
                )

        metadata = input.get("metadata", {})
        # Keep SAP's DocEntry field and business partner code in the private meta data
        # so we can refer to this order again
        private_metadata = {
            "doc_entry": data["doc_entry"],
            "sap_bp_code": data["sap_bp_code"],
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

        # Lookup the shipping method by name and update the order
        if shipping_method_name:
            available_shipping_methods = get_valid_shipping_methods_for_order(order)
            shipping_method = available_shipping_methods.filter(
                private_metadata__TrnspName=shipping_method_name
            ).first()
            order.shipping_method = shipping_method
            order.shipping_method_name = shipping_method.name
            order.save()

        if input.get("confirm_order", False):
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
