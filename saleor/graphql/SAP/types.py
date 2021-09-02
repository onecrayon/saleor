import graphene
from graphene import relay
from graphene_federation import key
from promise import Promise

from firstech.SAP import models
from saleor.account.models import User as UserModel

from ...account.utils import requestor_is_staff_member_or_app
from ...core.tracing import traced_resolver
from ...graphql.utils import get_user_or_app_from_context
from ..channel import ChannelContext
from ..channel.dataloaders import ChannelByOrderLineIdLoader
from ..core.connection import CountableDjangoObjectType
from ..core.types import Error
from ..core.types.money import Money
from ..product.dataloaders import (
    ProductChannelListingByProductIdAndChannelSlugLoader,
    ProductVariantByIdLoader,
)


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

    class Meta:
        description = "Business partner"
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
    def resolve_drone_rewards_profile(root: models.BusinessPartner, _info, **kwargs):
        try:
            return root.dronerewardsprofile
        except models.DroneRewardsProfile.DoesNotExist:
            return None


@key("id")
class SAPUserProfile(CountableDjangoObjectType):
    business_partners = graphene.List(
        BusinessPartner, description="List of business partners this user belongs to."
    )

    class Meta:
        description = "SAP User Profile"
        model = models.SAPUserProfile
        interfaces = [relay.Node]
        only_fields = [
            "user",
            "date_of_birth",
            "is_company_owner",
        ]

    @staticmethod
    def resolve_business_partners(root: models.SAPUserProfile, _info, **kwargs):
        return root.business_partners.all()


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
        """This whole mess is copy/pasted over from the OrderLine type. It appears to
        do some permission checking. Also if you don't use those dataloader classes
        the resolver will crash and burn because it's looking for a ChannelContext type.
        """

        context = info.context
        if not root.product_variant_id:
            return None

        def requestor_has_access_to_variant(data):
            variant, channel = data

            requester = get_user_or_app_from_context(context)
            is_staff = requestor_is_staff_member_or_app(requester)
            if is_staff:
                return ChannelContext(node=variant, channel_slug=channel.slug)

            def product_is_available(product_channel_listing):
                if product_channel_listing and product_channel_listing.is_visible:
                    return ChannelContext(node=variant, channel_slug=channel.slug)
                return None

            return (
                ProductChannelListingByProductIdAndChannelSlugLoader(context)
                .load((variant.product_id, channel.slug))
                .then(product_is_available)
            )

        variant = ProductVariantByIdLoader(context).load(root.product_variant_id)
        channel = ChannelByOrderLineIdLoader(context).load(root.id)

        return Promise.all([variant, channel]).then(requestor_has_access_to_variant)


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
    def resolve_price(root: "models.SAPReturnLine", _info):
        return root.unit_price

    @staticmethod
    @traced_resolver
    def resolve_variant(root, info):
        """This whole mess is copy/pasted over from the OrderLine type. It appears to
        do some permission checking. Also if you don't use those dataloader classes
        the resolver will crash and burn because it's looking for a ChannelContext type.
        """

        context = info.context
        if not root.product_variant_id:
            return None

        def requestor_has_access_to_variant(data):
            variant, channel = data

            requester = get_user_or_app_from_context(context)
            is_staff = requestor_is_staff_member_or_app(requester)
            if is_staff:
                return ChannelContext(node=variant, channel_slug=channel.slug)

            def product_is_available(product_channel_listing):
                if product_channel_listing and product_channel_listing.is_visible:
                    return ChannelContext(node=variant, channel_slug=channel.slug)
                return None

            return (
                ProductChannelListingByProductIdAndChannelSlugLoader(context)
                .load((variant.product_id, channel.slug))
                .then(product_is_available)
            )

        variant = ProductVariantByIdLoader(context).load(root.product_variant_id)
        channel = ChannelByOrderLineIdLoader(context).load(root.id)

        return Promise.all([variant, channel]).then(requestor_has_access_to_variant)


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
