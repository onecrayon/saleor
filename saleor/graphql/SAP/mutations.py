import graphene

from firstech.SAP import PricingList, models
from saleor.checkout import AddressType
from saleor.core.permissions import AccountPermissions
from saleor.graphql.account.enums import AddressTypeEnum
from saleor.graphql.account.types import AddressInput
from saleor.graphql.core.mutations import ModelMutation
from saleor.graphql.core.scalars import Decimal
from saleor.graphql.core.types.common import BusinessPartnerError, AccountError
from saleor.graphql.SAP.types import BusinessPartner, SAPUserProfile, SAPApprovedBrands


PricingListEnum = graphene.Enum(
    "PricingList",
    [(pricing_list[0], pricing_list[0]) for pricing_list in PricingList.CHOICES]
)


class BusinessPartnerCreateInput(graphene.InputObjectType):
    addresses = graphene.List(of_type=graphene.ID)
    account_balance = Decimal()
    account_is_active = graphene.Boolean()
    account_purchasing_restricted = graphene.Boolean()
    card_code = graphene.String(required=True)
    company_name = graphene.String()
    company_url = graphene.String()
    credit_limit = Decimal()
    customer_type = graphene.String()
    debit_limit = Decimal()
    # drone_rewards
    inside_sales_rep = graphene.String()
    internal_ft_notes = graphene.String()
    outside_sales_rep = graphene.String()
    outside_sales_rep_emails = graphene.List(of_type=graphene.String)
    payment_terms = graphene.String()
    pricing_list = PricingListEnum(description="Prcing lists.")
    sales_manager = graphene.String()
    sap_bp_code = graphene.String()
    shipping_preference = graphene.String()
    sync_partner = graphene.Boolean()
    warranty_preference = graphene.String()


class MigrateBusinessPartner(ModelMutation):
    """Mutation for creating (i.e. migrating over) a business partner from SAP"""
    business_partner = graphene.Field(
        BusinessPartner,
        description="A business partner instance that was created."
    )

    class Arguments:
        input = BusinessPartnerCreateInput(
            description="Fields required to create business partner.",
            required=True
        )

    class Meta:
        description = "Create a new SAP business partner inside Saleor."
        exclude = []
        model = models.BusinessPartner
        permissions = (AccountPermissions.MANAGE_USERS,)
        error_type_class = BusinessPartnerError
        error_type_field = "business_partner_errors"


class BusinessPartnerAddressCreate(ModelMutation):
    business_partner = graphene.Field(
        BusinessPartner,
        description="A business partner instance for which the address was created."
    )

    class Arguments:
        business_partner_id = graphene.ID(
            description="ID of a business partner to create address for.",
            required=True
        )
        input = AddressInput(
            description="Fields required to create address.", required=True
        )
        type = AddressTypeEnum(
            required=False,
            description=(
                "A type of address. If provided, the new address will be "
                "automatically assigned as the business partner's default address "
                "of that type."
            ),
        )

    class Meta:
        description = "Creates a business partner address."
        model = models.Address
        permissions = (AccountPermissions.MANAGE_USERS,)
        error_type_class = AccountError
        error_type_field = "account_errors"

    @classmethod
    def perform_mutation(cls, root, info, **data):
        address_type = data.get("type", None)
        business_partner_id = data["business_partner_id"]
        business_partner = cls.get_node_or_error(
            info,
            business_partner_id,
            field="business_partner_id",
            only_type=BusinessPartner
        )
        response = super().perform_mutation(root, info, **data)
        if not response.errors:
            business_partner.addresses.add(response.address)
            response.business_partner = business_partner
            if address_type:
                if address_type == AddressType.BILLING:
                    business_partner.default_billing_address = response.address
                elif address_type == AddressType.SHIPPING:
                    business_partner.default_shipping_address = response.address
                business_partner.save()
        return response


class SAPUserProfileCreateInput(graphene.InputObjectType):
    user = graphene.ID()
    date_of_birth = graphene.String()
    is_company_owner = graphene.Boolean()
    middle_name = graphene.String()
    business_partner_id = graphene.ID()


class CreateSAPUserProfile(ModelMutation):
    """Mutation for creating a user's SAP user profile"""
    sap_user_profile = graphene.Field(
        SAPUserProfile,
        description="An SAP user profile that was created."
    )

    class Arguments:
        input = SAPUserProfileCreateInput(
            description="Fields required to create SAP user profile.",
            required=True
        )

    class Meta:
        description = "Create a new SAP user profile."
        exclude = []
        model = models.SAPUserProfile
        permissions = (AccountPermissions.MANAGE_USERS,)
        error_type_class = BusinessPartnerError
        error_type_field = "business_partner_errors"


class SAPApprovedBrandsInput(graphene.InputObjectType):
    # TODO: Should this be a list of enum types instead?
    momento = graphene.Boolean()
    tesa = graphene.Boolean()
    idatalink = graphene.Boolean()
    maestro = graphene.Boolean()
    compustar = graphene.Boolean()
    compustar_pro = graphene.Boolean()
    ftx = graphene.Boolean()
    arctic_start = graphene.Boolean()
    compustar_mesa_only = graphene.Boolean()
    replacements = graphene.Boolean()


class AssignApprovedBrands(ModelMutation):
    """Mutation for assigning approved brands to a business partner"""
    approved_brands = graphene.Field(
        SAPApprovedBrands,
        description="The approved brands for this business partner."
    )

    class Arguments:
        business_partner_id = graphene.ID(
            description="ID of a business partner to create address for.",
            required=True
        )
        input = SAPApprovedBrandsInput(
            description="List of approved brands to assign.",
            required=True
        )

    class Meta:
        description = "Assign brands to an SAP business partner."
        exclude = []
        model = models.ApprovedBrands
        permissions = (AccountPermissions.MANAGE_USERS,)
        error_type_class = BusinessPartnerError
        error_type_field = "business_partner_errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        """Update the existing approved-brands for the business partner if it already
        exists. If one does not exist already, create one."""

        business_partner_id = data["business_partner_id"]
        business_partner = cls.get_node_or_error(
            info,
            business_partner_id,
            field="business_partner_id",
            only_type=BusinessPartner
        )

        # Get or create the approved brands
        try:
            approved_brands = business_partner.approvedbrands
        except models.ApprovedBrands.DoesNotExist:
            approved_brands = models.ApprovedBrands(
                business_partner=business_partner
            )

        # Update based on the input
        for brand, value in data["input"].items():
            setattr(approved_brands, brand, value)

        approved_brands.save()

        return cls.success_response(approved_brands)
