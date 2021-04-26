import graphene

from firstech.SAP import models
from saleor.graphql.SAP.mutations import (
    CreateSAPUserProfile,
    MigrateBusinessPartner
)
from ...core.exceptions import PermissionDenied
from ...core.permissions import AccountPermissions
from ..core.fields import FilterInputConnectionField
from ..decorators import permission_required
from ..utils import get_user_or_app_from_context
from .types import BusinessPartner, SAPUserProfile


class SAPQueries(graphene.ObjectType):
    sap_profile = graphene.Field(
        SAPUserProfile,
        id=graphene.Argument(
            graphene.ID,
            description="ID of the SAP profile description in schema def"
        ),
    )
    business_partner = graphene.Field(
        BusinessPartner,
        id=graphene.Argument(graphene.ID, description="ID of the business partner.")
    )
    business_partners = FilterInputConnectionField(
        BusinessPartner,
        description="List of the shop's business partners.",
    )

    @permission_required(AccountPermissions.MANAGE_USERS)
    def resolve_business_partner(self, info, id=None, query=None, **kwargs):
        requester = get_user_or_app_from_context(info.context)
        if requester:
            filter_kwargs = {}
            _model, filter_kwargs["pk"] = graphene.Node.from_global_id(id)
            return models.BusinessPartner.objects.filter(**filter_kwargs).first()

        return PermissionDenied()

    @permission_required(AccountPermissions.MANAGE_USERS)
    def resolve_business_partners(self, info, query=None, **kwargs):
        requester = get_user_or_app_from_context(info.context)
        if requester:
            filter_kwargs = {}
            # TODO Support filtering
            return models.BusinessPartner.objects.filter(**filter_kwargs).all()

        return PermissionDenied()


class SAPMutations(graphene.ObjectType):
    business_partner_migrate = MigrateBusinessPartner.Field()
    create_sap_profile = CreateSAPUserProfile.Field()
