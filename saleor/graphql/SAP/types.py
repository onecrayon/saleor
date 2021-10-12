import graphene
from graphene import relay
from graphene_federation import key

from firstech.permissions import SAPCustomerPermissions, SAPStaffPermissions
from firstech.SAP import models
from saleor.account.models import User as UserModel
from saleor.order.models import Order as OrderModel
from saleor.core.permissions import AccountPermissions, OrderPermissions
from ..core.fields import PrefetchingConnectionField

from ...core.tracing import traced_resolver
from ..core.connection import CountableDjangoObjectType
from ..core.types import Error
from ..core.types.money import Money


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
        fields = "__all__"


class DroneRewardsProfile(CountableDjangoObjectType):
    class Meta:
        description = "Define the drone rewards information for a dealer."
        permissions = (SAPCustomerPermissions.VIEW_DRONE_REWARDS,)
        model = models.DroneRewardsProfile
        interfaces = [relay.Node]
        fields = "__all__"


@key("id")
@key("sapBpCode")
class BusinessPartner(CountableDjangoObjectType):
    """Business partners can be looked up using either their id or cardCode."""

    company_contacts = graphene.List(
        "saleor.graphql.account.types.User",
        description="List of users at this business partner.",
    )
    approved_brands = graphene.List(
        graphene.String,
        description="List of approved brands for this business partner.",
    )
    drone_rewards_profile = graphene.Field(
        DroneRewardsProfile, description="Drone rewards information for the dealer."
    )
    orders = graphene.List(
        "saleor.graphql.order.types.Order",
        description="List of business partner's orders."
    )

    class Meta:
        description = "Business partner"
        permissions = ()
        model = models.BusinessPartner
        interfaces = [relay.Node]
        fields = "__all__"

    @staticmethod
    def resolve_company_contacts(root: models.BusinessPartner, _info, **kwargs):
        return UserModel.objects.filter(sapuserprofile__business_partners=root)

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
    def resolve_drone_rewards_profile(root: models.BusinessPartner, info, **kwargs):
        requesting_user = info.context.user
        if requesting_user.has_perm(SAPCustomerPermissions.VIEW_DRONE_REWARDS):
            try:
                return root.dronerewardsprofile
            except models.DroneRewardsProfile.DoesNotExist:
                return None
        else:
            return None

    @staticmethod
    def resolve_sapuserprofiles(root: models.BusinessPartner, info, **kwargs):
        requesting_user = info.context.user
        if (
                requesting_user.has_perm(SAPCustomerPermissions.MANAGE_LINKED_INSTALLERS)
                or requesting_user.has_perm(AccountPermissions.MANAGE_USERS)
            ):
            return root.sapuserprofiles
        elif requesting_user.has_perm(SAPCustomerPermissions.VIEW_PROFILE):
            # Without elevated privileges only show the requesting user's own profile
            return root.sapuserprofiles.filter(user=requesting_user)
        else:
            return []

    @staticmethod
    def resolve_orders(root: models.BusinessPartner, info, **kwargs):
        requesting_user = info.context.user
        if (
                requesting_user.has_perm(SAPCustomerPermissions.MANAGE_BP_ORDERS)
                or requesting_user.has_perm(OrderPermissions.MANAGE_ORDERS)
        ):
            return OrderModel.objects.filter(
                private_metadata__sap_bp_code=root.sap_bp_code
            )
        else:
            return []


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
        only_fields = [
            "user",
            "date_of_birth",
            "middle_name"
        ]

    @staticmethod
    def resolve_business_partners(root: models.SAPUserProfile, _info, **kwargs):
        return root.business_partners.all()

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
        Money,
        description="The price at which the item was returned for."
    )
    variant = graphene.Field(
        "saleor.graphql.product.types.ProductVariant",
        description="The product variant of the returned item."
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
        SAPReturnLine,
        description="The list of line items included in the return."
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
        Money,
        description="The price at which the item was returned for."
    )
    variant = graphene.Field(
        "saleor.graphql.product.types.ProductVariant",
        description="The product variant of the credited item."
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
        description="The list of line items included in the credit memo."
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
