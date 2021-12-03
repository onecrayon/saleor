import graphene
from django.core.exceptions import ValidationError

from firstech.permissions import SAPCustomerPermissions, SAPStaffPermissions
from firstech.SAP.models import BusinessPartner
from saleor.checkout import models
from saleor.graphql.checkout.mutations import CheckoutCreate, CheckoutCreateInput
from saleor.graphql.core.types.common import CheckoutError
from saleor.graphql.utils import get_user_or_app_from_context


class B2BCheckoutCreateInput(CheckoutCreateInput):
    sap_bp_code = graphene.String(
        required=True, description="Card code of the business partner for the order."
    )


class B2BCheckoutCreate(CheckoutCreate):
    """Functionally identical to Saleor's CheckoutCreate mutation but we require the
    request also contains the business partner's card code."""

    class Arguments:
        input = B2BCheckoutCreateInput(
            required=True, description="Fields required to create checkout."
        )

    class Meta:
        description = "Create a new B2B checkout."
        model = models.Checkout
        permissions = (SAPCustomerPermissions.PURCHASE_PRODUCTS_B2B,)
        return_field_name = "checkout"
        error_type_class = CheckoutError
        error_type_field = "checkout_errors"

    @classmethod
    def clean_input(cls, info, instance: models.Checkout, data, input_cls=None):
        requester = get_user_or_app_from_context(info.context)
        try:
            business_partner = BusinessPartner.objects.get(
                sap_bp_code=data["sap_bp_code"]
            )
        except BusinessPartner.DoesNotExist:
            raise ValidationError("Business partner with that card code does not exist")

        # The requester must either belong to the business partner, be a staff user with
        # the place-orders-for-dealer permission or be connected to the business partner
        # as a sales rep or sales manager with the place-orders-for-linked-accounts
        # permission. We already know that the requester has the purchase-products-b2b
        # permission since the mutation is entirely off limits without it.
        if not (
            requester.has_perm(SAPStaffPermissions.PLACE_ORDERS_FOR_DEALER)
            or business_partner.sapuserprofiles.filter(user=requester).exists()
            or (
                requester.has_perm(
                    SAPCustomerPermissions.PLACE_ORDERS_FOR_LINKED_ACCOUNTS
                )
                and (
                    business_partner.inside_sales_rep_id == requester.id
                    or business_partner.sales_manager_id == requester.id
                    or requester in business_partner.outside_sales_rep.all()
                )
            )
        ):
            raise PermissionError(
                "You do not have permission to create orders for this business partner."
            )

        cleaned_input = super().clean_input(info, instance, data, input_cls=input_cls)
        cleaned_input["private_metadata"] = {"sap_bp_code": data["sap_bp_code"]}

        return cleaned_input
