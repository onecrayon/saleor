import graphene
from graphene import relay
from graphene_federation import key

from firstech.permissions import SAPCustomerPermissions
from firstech.SAP import models
from saleor.account.models import User as UserModel
from saleor.core.permissions import (
    AccountPermissions,
    OrderPermissions,
    has_one_of_permissions,
)
from saleor.graphql.SAP.dataloaders import OrdersByBusinessPartnerLoader

from ...core.tracing import traced_resolver
from ..core.connection import CountableDjangoObjectType
from ..core.fields import PrefetchingConnectionField
from ..core.types import Error
from ..core.types.money import Money
from ..decorators import one_of_permissions_required, permission_required
from ..utils import get_user_or_app_from_context
from .resolvers import filter_business_partner_by_view_permissions


class BusinessPartnerError(Error):
    code = graphene.String(description="The error code.", required=True)


class SAPApprovedBrands(CountableDjangoObjectType):
    @property
    def fields(self):
        return [
            "momento",
            "tesa",
            "idatalink",
            "maestro",
            "compustar",
            "compustar_pro",
            "ftx",
            "arctic_start",
            # Not a field currently but will be added to SAP in the future
            "compustar_mesa_only",
            "replacements",
        ]

    class Meta:
        description = "Approved brands from SAP"
        model = models.ApprovedBrands
        interfaces = [relay.Node]
        fields = (
            "business_partner",
            "momento",
            "tesa",
            "idatalink",
            "maestro",
            "compustar",
            "compustar_pro",
            "ftx",
            "arctic_start",
            "compustar_mesa_only",
            "replacements",
        )


class DroneRewardsProfile(CountableDjangoObjectType):
    class Meta:
        description = "Define the drone rewards information for a dealer."
        permissions = (SAPCustomerPermissions.VIEW_DRONE_REWARDS,)
        model = models.DroneRewardsProfile
        interfaces = [relay.Node]
        fields = (
            "business_partner",
            "enrolled",
            "onboarded",
            "distribution",
        )


@key("id")
@key("sapBpCode")
class BusinessPartner(CountableDjangoObjectType):
    """Business partners can be looked up using either their id or cardCode. Many of the
    fields have resolvers specified for them for the sole purpose of restricting them
    by permissions."""

    company_contacts = graphene.List(
        "saleor.graphql.account.types.RedactedUser",
        description="List of users at this business partner.",
    )
    approved_brands = graphene.List(
        graphene.String,
        description="List of approved brands for this business partner.",
    )
    drone_rewards_profile = graphene.Field(
        DroneRewardsProfile, description="Drone rewards information for the dealer."
    )
    orders = PrefetchingConnectionField(
        "saleor.graphql.order.types.Order",
        description="List of business partner's orders.",
    )
    inside_sales_rep = graphene.Field("saleor.graphql.account.types.RedactedUser")
    outside_sales_rep = graphene.List("saleor.graphql.account.types.RedactedUser")
    sales_manager = graphene.Field("saleor.graphql.account.types.RedactedUser")
    addresses = graphene.List("saleor.graphql.account.types.Address")

    class Meta:
        description = "Business partner"
        model = models.BusinessPartner
        interfaces = [relay.Node]
        fields = (
            "addresses",
            "account_balance",
            "account_is_active",
            "account_purchasing_restricted",
            "company_name",
            "company_url",
            "credit_limit",
            "customer_type",
            "debit_limit",
            "default_shipping_address",
            "default_billing_address",
            "inside_sales_rep",
            "internal_ft_notes",
            "outside_sales_rep",
            "payment_terms",
            "channel",
            "sales_manager",
            "sap_bp_code",
            "shipping_preference",
            "sync_partner",
            "warranty_preference",
        )

    @staticmethod
    @permission_required(SAPCustomerPermissions.MANAGE_BP_ORDERS)
    def resolve_payment_terms(root, _info, **kwargs):
        return root.payment_terms

    @staticmethod
    @permission_required(SAPCustomerPermissions.MANAGE_BP_ORDERS)
    def resolve_channel(root, _info, **kwargs):
        return root.channel

    @staticmethod
    @permission_required(SAPCustomerPermissions.MANAGE_BP_ORDERS)
    def resolve_warranty_preference(root, _info, **kwargs):
        return root.channel

    @staticmethod
    @permission_required(SAPCustomerPermissions.VIEW_ACCOUNT_BALANCE)
    def resolve_account_balance(root, _info, **kwargs):
        return root.account_balance

    @staticmethod
    @permission_required(SAPCustomerPermissions.ACCESS_TO_LINKED_ACCOUNTS)
    def resolve_account_is_active(root, _info, **kwargs):
        return root.account_is_active

    @staticmethod
    @permission_required(SAPCustomerPermissions.ACCESS_TO_LINKED_ACCOUNTS)
    def resolve_account_is_purchasing_restricted(root, _info, **kwargs):
        return root.account_is_purchasing_restricted

    @staticmethod
    @permission_required(SAPCustomerPermissions.ACCESS_TO_LINKED_ACCOUNTS)
    def resolve_credit_limit(root, _info, **kwargs):
        return root.credit_limit

    @staticmethod
    @permission_required(SAPCustomerPermissions.ACCESS_TO_LINKED_ACCOUNTS)
    def resolve_debit_limit(root, _info, **kwargs):
        return root.debit_limit

    @staticmethod
    @one_of_permissions_required(
        [AccountPermissions.MANAGE_USERS, AccountPermissions.MANAGE_STAFF]
    )
    def resolve_internal_ft_notes(root: models.BusinessPartner, _info, **kwargs):
        return root.internal_ft_notes

    @staticmethod
    @one_of_permissions_required(
        [AccountPermissions.MANAGE_USERS, AccountPermissions.MANAGE_STAFF]
    )
    def resolve_sync_partner(root: models.BusinessPartner, _info, **kwargs):
        return root.sync_partner

    @staticmethod
    def resolve_company_contacts(root: models.BusinessPartner, _info, **kwargs):
        return root.company_contacts

    @staticmethod
    def resolve_approved_brands(root: models.BusinessPartner, _info, **kwargs):
        all_brands = SAPApprovedBrands().fields
        try:
            return [
                field
                for field in all_brands
                if getattr(root.approvedbrands, field) is True
            ]
        except models.ApprovedBrands.DoesNotExist:
            return []

    @staticmethod
    @permission_required(SAPCustomerPermissions.VIEW_DRONE_REWARDS)
    def resolve_drone_rewards_profile(root: models.BusinessPartner, _info, **kwargs):
        try:
            return root.dronerewardsprofile
        except models.DroneRewardsProfile.DoesNotExist:
            return None

    @staticmethod
    def resolve_sapuserprofiles(root: models.BusinessPartner, info, **kwargs):
        requester = get_user_or_app_from_context(info.context)
        if has_one_of_permissions(
            requester,
            [
                SAPCustomerPermissions.MANAGE_LINKED_INSTALLERS,
                AccountPermissions.MANAGE_USERS,
            ],
        ):
            return root.sapuserprofiles
        elif requester.has_perm(SAPCustomerPermissions.VIEW_PROFILE):
            # Without elevated privileges only show the requesting user's own profile
            return root.sapuserprofiles.filter(user=requester)
        else:
            return []

    @staticmethod
    def resolve_orders(root: models.BusinessPartner, info, **_kwargs):
        def _resolve_orders(orders):
            requester = get_user_or_app_from_context(info.context)
            if has_one_of_permissions(
                requester,
                [
                    OrderPermissions.MANAGE_ORDERS,
                    SAPCustomerPermissions.MANAGE_BP_ORDERS,
                ],
            ):
                return orders

            return []

        return (
            OrdersByBusinessPartnerLoader(info.context)
            .load(root.id)
            .then(_resolve_orders)
        )

    @staticmethod
    def resolve_addresses(root: models.BusinessPartner, _info, **kwargs):
        return root.addresses.annotate_default(root).all()

    @staticmethod
    def resolve_outside_sales_rep(root: models.BusinessPartner, _info, **kwargs):
        return root.outside_sales_rep.all()


class SAPSalesManager(CountableDjangoObjectType):
    class Meta:
        description = "SAP sales manager status"
        model = models.SAPSalesManager
        only_fields = [
            "name",
            "user",
        ]


@key("id")
class SAPUserProfile(CountableDjangoObjectType):
    business_partners = graphene.List(
        BusinessPartner, description="List of business partners this user belongs to."
    )
    sales_manager = graphene.Field(
        SAPSalesManager, description="Sales manager details."
    )

    class Meta:
        description = "SAP User Profile"
        model = models.SAPUserProfile
        interfaces = [relay.Node]
        only_fields = ["user", "date_of_birth", "middle_name"]

    @staticmethod
    def resolve_business_partners(root: models.SAPUserProfile, info, **kwargs):
        requester = get_user_or_app_from_context(info.context)
        return filter_business_partner_by_view_permissions(
            root.business_partners.all(), requester
        )

    @staticmethod
    def resolve_sales_manager(root: models.SAPUserProfile, _info, **kwargs):
        # This allows a user who is a sales manager to see what their "name" is in SAP
        try:
            return root.user.sapsalesmanager
        except models.SAPSalesManager.DoesNotExist:
            return None


class SAPProductError(Error):
    code = graphene.String(description="The error code.", required=True)


class OutsideSalesRep(CountableDjangoObjectType):
    class Meta:
        description = "Outside Sales Rep"
        model = models.OutsideSalesRep
        interfaces = [relay.Node]
        only_fields = [
            "name",
            "user",
            "business_partner",
        ]


class SAPReturnLine(CountableDjangoObjectType):

    price = graphene.Field(
        Money, description="The price at which the item was returned for."
    )
    variant = graphene.Field(
        "saleor.graphql.product.types.ProductVariant",
        description="The product variant of the returned item.",
    )

    class Meta:
        description = "Line item in an SAP return document."
        model = models.SAPReturnLine
        interfaces = [relay.Node]
        only_fields = [
            "quantity",
            "variant",
        ]

    @staticmethod
    def resolve_price(root: "models.SAPReturnLine", _info):
        return root.unit_price

    @staticmethod
    @traced_resolver
    def resolve_variant(root, info):
        # Need to import here to avoid circular import
        from saleor.graphql.order.types import OrderLine

        return OrderLine.resolve_variant(root, info)


class SAPReturn(CountableDjangoObjectType):
    lines = graphene.List(
        SAPReturnLine, description="The list of line items included in the return."
    )

    class Meta:
        description = "SAP Return Document"
        model = models.SAPReturn
        interfaces = [relay.Node]
        only_fields = [
            "doc_entry",
            "create_date",
            "business_partner",
            "order",
            "remarks",
            "purchase_order",
            "lines",
            "total",
            "total_net",
            "total_gross",
        ]

    @staticmethod
    def resolve_lines(root: models.SAPReturn, _info):
        return root.lines.all()


class SAPCreditMemoLine(CountableDjangoObjectType):

    price = graphene.Field(
        Money, description="The price at which the item was returned for."
    )
    variant = graphene.Field(
        "saleor.graphql.product.types.ProductVariant",
        description="The product variant of the credited item.",
    )

    class Meta:
        description = "Line item in an SAP credit memo document."
        model = models.SAPCreditMemoLine
        interfaces = [relay.Node]
        only_fields = [
            "quantity",
            "variant",
        ]

    @staticmethod
    def resolve_price(root: "models.SAPCreditMemoLine", _info):
        return root.unit_price

    @staticmethod
    @traced_resolver
    def resolve_variant(root, info):
        # Need to import here to avoid circular import
        from saleor.graphql.order.types import OrderLine

        return OrderLine.resolve_variant(root, info)


class SAPCreditMemo(CountableDjangoObjectType):
    lines = graphene.List(
        SAPCreditMemoLine,
        description="The list of line items included in the credit memo.",
    )

    class Meta:
        description = "SAP Credit Memo Document"
        model = models.SAPCreditMemo
        interfaces = [relay.Node]
        only_fields = [
            "doc_entry",
            "create_date",
            "business_partner",
            "order",
            "remarks",
            "purchase_order",
            "lines",
            "total",
            "total_net",
            "total_gross",
            "refunded",
            "status",
        ]

    @staticmethod
    def resolve_lines(root: models.SAPCreditMemo, _info):
        return root.lines.all()
