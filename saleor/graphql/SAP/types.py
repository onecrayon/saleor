import graphene
from graphene import relay
from graphene_federation import key

from firstech.SAP import models
from saleor.account.models import User as UserModel

from ..core.connection import CountableDjangoObjectType


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


@key("id")
@key("cardCode")
class BusinessPartner(CountableDjangoObjectType):
    company_contacts = graphene.List(
        "saleor.graphql.account.types.User",
        description="List of users at this business partner."
    )
    approved_brands = graphene.List(
        graphene.String,
        description="List of approved brands for this business partner."
    )

    class Meta:
        description = "Business partner"
        model = models.BusinessPartner
        interfaces = [relay.Node]
        fields = "__all__"

    @staticmethod
    def resolve_company_contacts(root: models.BusinessPartner, _info, **kwargs):

        try:
            contact_ids = models.SAPUserProfile.objects.filter(
                business_partner=root
            ).values_list('user_id', flat=True)
            return UserModel.objects.filter(id__in=contact_ids).all()

        except models.SAPUserProfile.DoesNotExist:
            return None

    @staticmethod
    def resolve_approved_brands(root: models.BusinessPartner, _info, **kwargs):
        all_brands = SAPApprovedBrands().fields
        try:
            return [field for field in all_brands
                    if getattr(root.approvedbrands, field) is True]
        except models.ApprovedBrands.DoesNotExist:
            return []


@key("id")
class SAPUserProfile(CountableDjangoObjectType):
    class Meta:
        description = "SAP User Profile"
        model = models.SAPUserProfile
        interfaces = [relay.Node]
        only_fields = [
            "user",
            "date_of_birth",
            "is_company_owner",
            "business_partner",
        ]
