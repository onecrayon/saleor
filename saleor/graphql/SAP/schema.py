import graphene

from firstech.SAP import models
from saleor.graphql.SAP.mutations import (
    CreateSAPUserProfile,
    BulkMigrateContacts,
    MigrateBusinessPartner,
    BusinessPartnerAddressCreate,
    BulkBusinessPartnerAddressCreate,
    AssignApprovedBrands,
    CreateDroneRewardsProfile,
    UpsertSAPProduct,
)
from ...core.exceptions import PermissionDenied
from ...core.permissions import AccountPermissions
from ..core.fields import FilterInputConnectionField
from ..core.validators import validate_one_of_args_is_in_query
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
        id=graphene.Argument(
            graphene.ID,
            description="ID of the business partner to look up."
        ),
        sapBpCode=graphene.Argument(
            graphene.String,
            description="SAP card code of the business partner to look up."
        )
    )
    business_partners = FilterInputConnectionField(
        BusinessPartner,
        description="List of the shop's business partners.",
    )

    @permission_required(AccountPermissions.MANAGE_USERS)
    def resolve_business_partner(self, info, id=None, sapBpCode=None, query=None):
        validate_one_of_args_is_in_query("id", id, "sapBpCode", sapBpCode)
        requester = get_user_or_app_from_context(info.context)
        if requester:
            filter_kwargs = {}
            if id:
                _model, filter_kwargs["pk"] = graphene.Node.from_global_id(id)
            elif sapBpCode:
                filter_kwargs["sap_bp_code"] = sapBpCode

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
    bulk_migrate_contacts = BulkMigrateContacts.Field()
    business_partner_address_create = BusinessPartnerAddressCreate.Field()
    bulk_business_partner_address_create = BulkBusinessPartnerAddressCreate.Field()
    business_partner_assign_approved_brands = AssignApprovedBrands.Field()
    business_partner_drone_rewards_profile_create = CreateDroneRewardsProfile.Field()
    upsert_sap_product = UpsertSAPProduct.Field()
