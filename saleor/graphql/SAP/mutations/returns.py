import re
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import graphene
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q

from firstech.permissions import SAPCustomerPermissions
from firstech.SAP import ReturnStatus, models
from firstech.SAP.models import BusinessPartner
from saleor.core.permissions import OrderPermissions
from saleor.core.tracing import traced_atomic_transaction
from saleor.graphql.account.i18n import I18nMixin
from saleor.graphql.account.types import AddressInput
from saleor.graphql.core.mutations import ModelMutation
from saleor.graphql.core.types.common import OrderError
from saleor.graphql.order.mutations.draft_orders import (
    DraftOrderCreate,
    OrderLineCreateInput,
)
from saleor.graphql.product.types import ProductVariant
from saleor.graphql.SAP.enums import ReturnTypeEnum
from saleor.graphql.SAP.mutations.orders import UpsertSAPOrder
from saleor.graphql.SAP.resolvers import filter_business_partner_by_view_permissions
from saleor.order.error_codes import OrderErrorCode
from saleor.order.models import Fulfillment as FulfillmentModel
from saleor.order.models import Order
from saleor.product import models as product_models
from saleor.shipping.models import ShippingMethod

if TYPE_CHECKING:
    from saleor.plugins.manager import PluginsManager
    from saleor.plugins.sap_orders.plugin import SAPPlugin


class UpsertSAPReturnDocument(ModelMutation, I18nMixin):
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
        rma_number = sap_return.get("NumAtCard")
        if not rma_number:
            # Only sync returns that have an RMA number included in them
            return

        # Ideally the sales rep enters the RMA number that we generate for them, but
        # there is nothing stopping them from entering any string for an rma number.
        # This isn't really a problem, but we won't save the rma_base if it doesn't
        # match our usual pattern.
        if re.match(r"^D\d{6}((EX)|(CR)|(SP)|(AD))\d+", rma_number):
            rma_base = rma_number[:9]
        else:
            rma_base = None

        # Try and figure out which fulfillment this goes to which is kept in the
        # BaseEntry field
        order = None
        po_number = None
        try:
            delivery_doc_entry = sap_return.get("DocumentLines", [])[0]["BaseEntry"]
        except IndexError:
            pass
        else:
            if fulfillment := FulfillmentModel.objects.filter(
                private_metadata__doc_entry=delivery_doc_entry
            ).first():
                order = fulfillment.order
                po_number = order.metadata.get("po_number")

        business_partner = models.BusinessPartner.objects.get(
            sap_bp_code=sap_return["CardCode"]
        )
        if sap_return["DocCurrency"] == "$":
            # We currently only support USD but conceivably could accept others in the
            # future
            currency = "USD"
        else:
            raise ValidationError(f"Unknown currency: {sap_return['DocCurrency']}")

        if sap_return.get("Cancelled") == "tYES":
            status = ReturnStatus.CANCELED
        elif sap_return.get("Confirmed") == "tYES":
            status = ReturnStatus.APPROVED
        else:
            status = ReturnStatus.PENDING

        billing_address = UpsertSAPOrder.parse_address_string(sap_return["Address"])
        billing_address = cls.validate_address(billing_address, address_type="billing")
        billing_address.save()
        shipping_address = UpsertSAPOrder.parse_address_string(sap_return["Address2"])
        shipping_address = cls.validate_address(
            shipping_address, address_type="shipping"
        )
        shipping_address.save()

        # Figure out the shipping type
        shipping_method_name = None
        if shipping_method_code := sap_return.get("TransportationCode"):
            if shipping_method := ShippingMethod.objects.filter(
                private_metadata__TrnspCode=str(shipping_method_code)
            ).first():
                shipping_method_name = shipping_method.name
            else:
                # We have a special shipping method from SAP
                shipping_method = sap_plugin.fetch_shipping_type(shipping_method_code)
                shipping_method_name = shipping_method["Name"]

        try:
            _return, _ = models.SAPReturn.objects.update_or_create(
                business_partner=business_partner,
                rma_number=rma_number,
                defaults={
                    "doc_entry": sap_return["DocEntry"],
                    "rma_base": rma_base,
                    "doc_entry": sap_return["DocEntry"],
                    "sap_create_date": datetime.strptime(
                        sap_return.get("DocDate"), "%Y-%m-%d"
                    ),
                    "order": order,
                    "remarks": sap_return.get("Comments"),
                    "po_number": po_number,
                    "currency": currency,
                    "total_net_amount": Decimal(sap_return["DocTotal"])
                    - Decimal(sap_return["VatSum"]),
                    "total_gross_amount": Decimal(sap_return["DocTotal"]),
                    "status": status,
                    "billing_address": billing_address,
                    "shipping_address": shipping_address,
                    "shipping_method_name": shipping_method_name,
                },
            )
        except IntegrityError:
            raise ValidationError(
                "The RMA number in the return does not belong to the business partner "
                "specified."
            )

        # Organize all the existing line items on our return
        line_cache = {}
        for line in _return.lines.all():
            line_cache[line.variant.sku] = line

        for line in sap_return["DocumentLines"]:
            sku = line["ItemCode"]
            try:
                variant = product_models.ProductVariant.objects.get(sku=sku)
            except product_models.ProductVariant.DoesNotExist:
                raise ValidationError(f"The SKU {sku} does not exist in Saleor.")

            models.SAPReturnLine.objects.update_or_create(
                sap_return=_return,
                variant=variant,
                defaults={
                    "quantity": line["Quantity"],
                    "unit_price_amount": Decimal(line["Price"]),
                    "currency": currency,
                },
            )
            # Remove this line from the cache. Anything left at the end will be deleted
            if sku in line_cache:
                del line_cache[sku]

        # Remove any pre-existing line items that are missing from the SAP return
        models.SAPReturnLine.objects.filter(variant__sku__in=line_cache.keys()).delete()

        return cls.success_response(_return)


class RequestReturnInput(graphene.types.InputObjectType):
    lines = graphene.List(
        OrderLineCreateInput,
        required=True,
        description="List of order lines to request return for.",
    )
    return_type = ReturnTypeEnum(description="What type of return this request is for.")
    business_partner = graphene.ID(
        required=True, description="ID of the business partner this return belongs to."
    )
    shipping_address = AddressInput(
        description="Optional shipping address of the customer to use for an exchange "
        "type return. Defaults to the business partners saved shipping "
        "address."
    )
    shipping_method = graphene.ID(
        description="Optional ID of a selected shipping method to use for an exchange "
        "type return. Defaults to the business partner's saved shipping "
        "preference.",
        name="shippingMethod",
    )
    customer_note = graphene.String(
        description="A note from a customer (reason for return). Visible by customers "
        "in the order summary."
    )
    billing_address = AddressInput(
        description="Optional billing address of the customer. Defaults to the "
        "business partner's saved billing address."
    )
    po_number = graphene.String(
        description="Optional PO number to associate the return with."
    )
    order = graphene.ID(
        description="Optional ID of an Order to associate the return with."
    )


class RequestReturn(ModelMutation, I18nMixin):
    class Arguments:
        input = RequestReturnInput(description="Input for creating a return request.")

    class Meta:
        description = "Updates or creates returns for an order."
        model = models.SAPReturn
        permissions = (SAPCustomerPermissions.MANAGE_BP_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def clean_input(cls, info, instance, data, input_cls=None):

        shipping_address = data.pop("shipping_address", None)
        billing_address = data.pop("billing_address", None)
        cleaned_input = super().clean_input(info, instance, data)

        # Check requester has access to this business partner
        requester = info.context.user
        business_partner = cleaned_input["business_partner"]
        if not filter_business_partner_by_view_permissions(
            BusinessPartner.objects.filter(id=business_partner.id), requester
        ).exists():
            raise PermissionError()

        lines = data.pop("lines", None)
        cls.clean_lines(cleaned_input, lines)
        DraftOrderCreate.clean_addresses(
            info, instance, cleaned_input, shipping_address, billing_address
        )

        # We don't require linking a return to a specific order or fulfillment, but it
        # is possible if either order id or po_number are included in the request.
        order: Order = cleaned_input.get("order")
        po_number = cleaned_input.get("po_number")
        # Check that the order identified in the request belongs to the business partner
        if (
            order
            and order.private_metadata.get("sap_bp_code")
            != business_partner.sap_bp_code
        ):
            raise ValidationError(
                "The order ID supplied does not belong to the business partner."
            )

        if not order and po_number:
            # Look up an order from the supplied po number
            try:
                order = Order.objects.get(
                    metadata__po_number=po_number,
                    private_metadata__sap_bp_code=business_partner.sap_bp_code,
                )
                cleaned_input["order"] = order
            except Order.DoesNotExist:
                raise ValidationError(
                    "An order with that PO number does not exist for the business "
                    "partner."
                )
            except Order.MultipleObjectsReturned:
                raise ValidationError(
                    "Multiple orders with the supplied PO number exist."
                )

        elif order and po_number:
            # The requester has supplied the order ID and the po number. Check that they
            # match
            existing_order_po_number = order.metadata.get("po_number")
            if existing_order_po_number != po_number:
                raise ValidationError(
                    "The order specified by the order input does not have the "
                    "po number given in the po number input."
                )

        cleaned_input["currency"] = order.currency if order else "USD"
        cleaned_input["status"] = ReturnStatus.PENDING

        # Doc entry will be set when a matching return in SAP is upserted to Saleor
        cleaned_input["doc_entry"] = None

        return cleaned_input

    @classmethod
    def clean_lines(
        cls,
        cleaned_input,
        lines,
    ):
        """Transform variant ids into nodes and ensure the quantity of line items is
        greater than zero"""
        if lines:
            variant_ids = [line.get("variant_id") for line in lines]
            variants = cls.get_nodes_or_error(variant_ids, "variants", ProductVariant)
            quantities = [line.get("quantity") for line in lines]
            if not all(quantity > 0 for quantity in quantities):
                raise ValidationError(
                    {
                        "quantity": ValidationError(
                            "Ensure this value is greater than 0.",
                            code=OrderErrorCode.ZERO_QUANTITY,
                        )
                    }
                )
            cleaned_input["variants"] = variants
            cleaned_input["quantities"] = quantities

    @classmethod
    @traced_atomic_transaction()
    def save(cls, info, instance, cleaned_input):
        """
        We need to assign a unique rma_number to the instance we create. The "base"
        or prefix of the rma is fixed, but a suffix is added to create unique numbers
        for returns that have the same base. This creates a potential race condition
        problem if two or more returns with the same base are created near the same
        time. Because we need to read from the database what, if any, pre-existing
        returns match the rma base then increment it by one. To avoid this, we'll
        insert the return to the database without an rma number. Then select and update
        all returns with the matching base rma number with a lock on those rows.

        Our current RA# formula is:
            C/D (Consumer/Dealer)
            Today’s date (MMDDYY)
            CR/EX/AD/SP (Warranty exchange type)
            Rising number (to differentiate the RAs created on that day)
        """
        # Save any addresses
        shipping_address = cleaned_input.get("shipping_address")
        if shipping_address:
            shipping_address.save()
            instance.shipping_address = shipping_address.get_copy()
        billing_address = cleaned_input.get("billing_address")
        if billing_address:
            billing_address.save()
            instance.billing_address = billing_address.get_copy()

        # Save the instance without an RMA number yet
        instance.save()

        # Build up the RMA number
        rma_base = "D" + datetime.now().strftime("%m%d%y")
        if instance.return_type == ReturnTypeEnum.CREDIT:
            rma_base += "CR"
        elif instance.return_type == ReturnTypeEnum.EXCHANGE:
            rma_base += "EX"
        elif instance.return_type == ReturnTypeEnum.ADVANCE:
            rma_base += "AD"
        elif instance.return_type == ReturnTypeEnum.SPECIAL:
            rma_base += "SP"

        # Get all returns that have the matching rma pattern, and include the instance
        # we just saved.
        rma_matching_pattern = (
            models.SAPReturn.objects.filter(Q(rma_base=rma_base) | Q(id=instance.id))
            .order_by("-id")
            .select_for_update()
        )
        with transaction.atomic():
            # queryset is evaluated here, and puts a lock on all the rows within
            new_return = rma_matching_pattern[0]
            try:
                previous_return = rma_matching_pattern[1]
                # The rma base is always 9 characters long
                previous_suffix = int(previous_return.rma_number[9:])
            except IndexError:
                # The return we just created is the only return with that rma base yet
                previous_suffix = 0

            new_return.rma_base = rma_base
            new_return.rma_number = rma_base + str(previous_suffix + 1)
            new_return.save()

        # Attach the line items
        return_lines = []
        for line in cleaned_input.get("lines", []):
            _, variant_id = graphene.Node.from_global_id(line["variant_id"])
            return_lines.append(
                models.SAPReturnLine(
                    sap_return=instance,
                    variant_id=variant_id,
                    quantity=line["quantity"],
                )
            )
        models.SAPReturnLine.objects.bulk_create(return_lines)
