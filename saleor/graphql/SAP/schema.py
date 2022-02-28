import graphene

from firstech.SAP import models
from saleor.graphql.SAP.mutations.business_partners import (
    AssignApprovedBrands,
    BusinessPartnerAddressCreate,
    CreateDroneRewardsProfile,
    CreateSAPUserProfile,
    UpsertBusinessPartner,
    CreateSalesManager,
)
from saleor.graphql.SAP.mutations.credit_memos import UpsertSAPCreditMemoDocument
from saleor.graphql.SAP.mutations.deliveries import UpsertSAPDeliveryDocument
from saleor.graphql.SAP.mutations.invoices import UpsertSAPInvoiceDocument
from saleor.graphql.SAP.mutations.orders import (
    UpsertSAPOrder,
    FirstechOrderLineUpdate,
    FirstechOrderLineDelete,
)
from saleor.graphql.SAP.mutations.products import UpsertSAPProduct
from saleor.graphql.SAP.mutations.returns import UpsertSAPReturnDocument, RequestReturn
from saleor.graphql.SAP.mutations.permission_group import (
    CustomerPermissionGroupCreate,
    CustomerPermissionGroupUpdate,
)

from .resolvers import (
    resolve_business_partner,
    filter_business_partner_by_view_permissions,
)

from ...core.exceptions import PermissionDenied
from ..core.fields import FilterInputConnectionField
from ..utils import get_user_or_app_from_context
from .sap_types import BusinessPartner, SAPUserProfile


class SAPQueries(graphene.ObjectType):
    sap_profile = graphene.Field(
        SAPUserProfile,
        id=graphene.Argument(graphene.ID, description="ID of the SAP profile."),
    )
    business_partner = graphene.Field(
        BusinessPartner,
        id=graphene.Argument(
            graphene.ID, description="ID of the business partner to look up."
        ),
        sapBpCode=graphene.Argument(
            graphene.String,
            description="SAP card code of the business partner to look up.",
        ),
        resolver=resolve_business_partner,
    )
    business_partners = FilterInputConnectionField(
        BusinessPartner,
        description="List of the shop's business partners.",
    )

    def resolve_business_partners(self, info, **kwargs):
        requester = get_user_or_app_from_context(info.context)
        if requester:
            filter_kwargs = {}
            # TODO Support filtering
            queryset = models.BusinessPartner.objects.filter(**filter_kwargs).all()
            return filter_business_partner_by_view_permissions(queryset, requester)

        return PermissionDenied()


class SAPMutations(graphene.ObjectType):
    upsert_business_partner = UpsertBusinessPartner.Field()
    create_sap_profile = CreateSAPUserProfile.Field()
    business_partner_address_create = BusinessPartnerAddressCreate.Field()
    business_partner_assign_approved_brands = AssignApprovedBrands.Field()
    business_partner_drone_rewards_profile_create = CreateDroneRewardsProfile.Field()
    upsert_sap_product = UpsertSAPProduct.Field()
    upsert_sap_order = UpsertSAPOrder.Field()
    upsert_sap_delivery = UpsertSAPDeliveryDocument.Field()
    upsert_sap_invoice = UpsertSAPInvoiceDocument.Field()
    upsert_sap_return = UpsertSAPReturnDocument.Field()
    upsert_sap_credit_memo = UpsertSAPCreditMemoDocument.Field()
    create_sales_manager = CreateSalesManager.Field()
    create_customer_permission_group = CustomerPermissionGroupCreate.Field()
    update_customer_permission_group = CustomerPermissionGroupUpdate.Field()
    firstech_order_line_update = FirstechOrderLineUpdate.Field()
    firstech_order_line_delete = FirstechOrderLineDelete.Field()
    request_return = RequestReturn.Field()
