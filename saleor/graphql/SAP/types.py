import graphene
from graphene import relay
from graphene_federation import key

from firstech.SAP import models
from saleor.account.models import User as UserModel

from ..core.connection import CountableDjangoObjectType
from ..core.types import Error


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
