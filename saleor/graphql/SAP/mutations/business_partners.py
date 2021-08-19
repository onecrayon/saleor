import graphene
from django.core.exceptions import ValidationError

from firstech.SAP import models
from saleor.account import models as user_models
from saleor.checkout import AddressType
from saleor.core.permissions import AccountPermissions
from saleor.graphql.account.enums import AddressTypeEnum
from saleor.graphql.account.mutations.staff import CustomerCreate
from saleor.graphql.account.types import AddressInput, User
from saleor.graphql.core.mutations import ModelMutation
from saleor.graphql.core.scalars import Decimal
from saleor.graphql.core.types.common import AccountError
from saleor.graphql.SAP.enums import DistributionTypeEnum
from saleor.graphql.SAP.types import (
    BusinessPartner,
    BusinessPartnerError,
    DroneRewardsProfile,
    OutsideSalesRep,
    SAPApprovedBrands,
    SAPUserProfile,
)


class GetBusinessPartnerMixin:
    @classmethod
    def get_business_partner(cls, data: dict, info):
        """Gets a business partner model object from either the base-64 encoded
        business partner id, or from an SAP card code. If both are provided, this will
        default to using the business partner ID."""
        if business_partner_id := data.get("business_partner_id"):
            business_partner = cls.get_node_or_error(
                info,
                business_partner_id,
                field="business_partner_id",
                only_type=BusinessPartner,
            )
        elif sap_bp_code := data.get("sap_bp_code"):
            business_partner = models.BusinessPartner.objects.filter(
                sap_bp_code=sap_bp_code
            ).first()
        else:
            return None

        return business_partner


class BusinessPartnerCreateInput(graphene.InputObjectType):
    addresses = graphene.List(of_type=graphene.ID)
    account_balance = Decimal()
    account_is_active = graphene.Boolean()
    account_purchasing_restricted = graphene.Boolean()
    company_name = graphene.String()
    company_url = graphene.String()
    credit_limit = Decimal()
    customer_type = graphene.String()
    debit_limit = Decimal()
    inside_sales_rep = graphene.String()
    internal_ft_notes = graphene.String()
    outside_sales_rep = graphene.List(of_type=graphene.String)
    outside_sales_rep_name = graphene.String()
    payment_terms = graphene.String()
    channel = graphene.ID()
    channel_name = graphene.String()
    sales_manager = graphene.String()
    sap_bp_code = graphene.String(required=True)
    shipping_preference = graphene.String()
    sync_partner = graphene.Boolean()
    warranty_preference = graphene.String()


class MigrateBusinessPartner(ModelMutation, GetBusinessPartnerMixin):
    """Mutation for creating (i.e. migrating over) a business partner from SAP. If the
    id argument is passed, then this will update the existing business partner with that
    id."""

    business_partner = graphene.Field(
        BusinessPartner, description="A business partner instance that was created."
    )

    class Arguments:
        business_partner_id = graphene.ID(
            description="ID of an existing business partner to update.",
        )
        sap_bp_code = graphene.String(
            description="SAP Card code of an existing business partner to update."
        )
        input = BusinessPartnerCreateInput(
            description="Fields required to create business partner.", required=True
        )

    class Meta:
        description = "Create a new SAP business partner inside Saleor."
        exclude = []
        model = models.BusinessPartner
        permissions = (AccountPermissions.MANAGE_USERS,)
        error_type_class = BusinessPartnerError
        error_type_field = "business_partner_errors"

    @classmethod
    def get_instance(cls, info, **data):
        """Retrieve an instance from the supplied global id, or by the "card_code" if it
        is supplied in the input data. This allows us to treat this mutation as a create
        or update based on the SAP card code which is unique.
        """
        instance = cls.get_business_partner(data, info)
        if not instance:
            instance = cls._meta.model()

        return instance

    @classmethod
    def clean_input(cls, info, instance, data, input_cls=None):
        """To avoid needing to make multiple queries with SAP integration framework,
        we're going to  resolve channel names into their django objects so that we don't
        have to look up what their base 64 id is
        """
        cleaned_input = super().clean_input(info, instance, data, input_cls=input_cls)
        if channel_name := data.pop("channel_name", None):
            channel = models.Channel.objects.filter(name=channel_name).first()
            cleaned_input["channel"] = channel

        if inside_sales_rep_email := data.pop("inside_sales_rep", None):
            cleaned_input["inside_sales_rep"] = user_models.User.objects.get(
                email=inside_sales_rep_email
            )

        if outside_sales_rep_emails := data.pop("outside_sales_rep", None):
            cleaned_input["outside_sales_rep"] = list(user_models.User.objects.filter(
                email__in=outside_sales_rep_emails
            ))

        return cleaned_input

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        instance = cls.get_instance(info, **data)
        data = data.get("input")
        cleaned_input = cls.clean_input(info, instance, data)
        instance = cls.construct_instance(instance, cleaned_input)
        cls.clean_instance(info, instance)
        cls.save(info, instance, cleaned_input)
        # Need to manually handle the m2m relationship on outside sales reps so that
        # we can set the 'name' field on the through table
        instance.outside_sales_rep.set(
            cleaned_input["outside_sales_rep"],
            through_defaults={"name": cleaned_input.get("outside_sales_rep_name")},
            clear=True
        )
        cls.post_save_action(info, instance, cleaned_input)
        return cls.success_response(instance)



class BusinessPartnerAddressCreate(ModelMutation, GetBusinessPartnerMixin):
    business_partner = graphene.Field(
        BusinessPartner,
        description="A business partner instance for which the address was created.",
    )

    class Arguments:
        business_partner_id = graphene.ID(
            description="ID of a business partner to create address for.",
        )
        sap_bp_code = graphene.String(description="Create Address for Card Code")
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
    def get_instance(cls, info, business_partner, **data) -> models.Address:
        """Get a django address model instance from information provided in data. If
        an address with the provided company_name, type (billing vs shipping), and
        business partner already exists, then returns that address. Otherwise returns
        a new address object.
        """
        address_type = data.get("type")
        company_name = data.get("input", {}).get("company_name")

        # Check to see if this address already exists
        # The SAP database doesn't keep a unique id for addresses, but an index on the
        # CRD1 table make the `Address`, `AdresType`, and `CardCode` fields
        # unique together which we can use to prevent duplicates from being created
        existing_address = models.Address.objects.filter(
            businesspartneraddresses__business_partner=business_partner,
            company_name=company_name,
            businesspartneraddresses__type=address_type,
        ).first()

        if existing_address:
            return existing_address
        else:
            return cls._meta.model()

    @classmethod
    def perform_mutation(cls, root, info, **data):
        address_type = data.get("type", None)
        business_partner: models.BusinessPartner = cls.get_business_partner(data, info)
        instance = cls.get_instance(info, business_partner, **data)
        # Check if the instance we got is an existing address or a new one
        # we will create. (This works because pk isn't set until saved to the db)
        if instance.pk:
            is_existing = True
        else:
            is_existing = False
        data = data.get("input")
        cleaned_input = cls.clean_input(info, instance, data, input_cls=AddressInput)
        instance = cls.construct_instance(instance, cleaned_input)
        cls.clean_instance(info, instance)
        cls.save(info, instance, cleaned_input)
        cls._save_m2m(info, instance, cleaned_input)
        cls.post_save_action(info, instance, cleaned_input)
        response = cls.success_response(instance)

        # If this is a new address, add it to the business partner
        if not is_existing:
            models.BusinessPartnerAddresses.objects.create(
                business_partner_id=business_partner.id,
                type=address_type,
                address_id=instance.id,
            )
            response.business_partner = business_partner
            # If this BP doesn't have default billing or shipping addresses, set them
            if address_type:
                if (
                    address_type == AddressType.BILLING
                    and not business_partner.default_billing_address
                ):
                    business_partner.default_billing_address = response.address
                elif (
                    address_type == AddressType.SHIPPING
                    and not business_partner.default_shipping_address
                ):
                    business_partner.default_shipping_address = response.address
                business_partner.save()
        return response


class BulkAddressInput(graphene.InputObjectType):
    type = AddressTypeEnum(
        required=False,
        description=(
            "A type of address. If provided, the new address will be "
            "automatically assigned as the business partner's default address "
            "of that type."
        ),
    )
    input = AddressInput(
        description="Fields required to create address.", required=True
    )
    business_partner_id = graphene.ID(
        description="ID of a business partner to create address for.",
    )
    sap_bp_code = graphene.String(description="Create Address for Card Code")


class BulkBusinessPartnerAddressCreate(BusinessPartnerAddressCreate):
    """Whenever a business partner (aka card-code) is updated in SAP it will trigger
    an event in the integration framework. We don't have a way of knowing what changed
    about the business partner. That means it's possible that existing addresses have
    been updated, new addresses created, or old addresses removed. It's also possible
    that addresses haven't been changed at all, but there's no way to know. So to work
    around that the integration framework is going to call this mutation to upsert all
    addresses for a business partner each time. This mutation will create, update, and
    remove from saleor accordingly."""

    class Arguments:
        input = graphene.List(of_type=BulkAddressInput)
        business_partner_id = graphene.ID(
            description="ID of a business partner to create address for.",
        )
        sap_bp_code = graphene.String(description="Create Address for Card Code")

    class Meta:
        description = "Creates many business partner addresses."
        model = models.Address
        permissions = (AccountPermissions.MANAGE_USERS,)
        error_type_class = AccountError
        error_type_field = "account_errors"

    @classmethod
    def perform_mutation(cls, root, info, **data):
        address_inputs = data.get("input")
        business_partner = cls.get_business_partner(data, info)

        existing_addresses = set(
            models.BusinessPartnerAddresses.objects.filter(
                business_partner=business_partner
            ).values_list("address__company_name", "type")
        )

        responses = []
        upserted_addresses = set()
        for address in address_inputs:
            response = super().perform_mutation(root, info, **address)
            responses.append(response)
            upserted_addresses.add((address["input"]["company_name"], address["type"]))

        # Remove any addresses that weren't included in the mutation
        addresses_to_delete = existing_addresses - upserted_addresses
        for company_name, address_type in addresses_to_delete:
            models.Address.objects.filter(
                businesspartneraddresses__business_partner=business_partner,
                businesspartneraddresses__type=address_type,
                company_name=company_name,
            ).delete()

        return cls(**{cls._meta.return_field_name: responses, "errors": []})


class DroneRewardsCreateInput(graphene.InputObjectType):
    business_partner = graphene.ID()
    distribution = DistributionTypeEnum()
    enrolled = graphene.Boolean()
    onboarded = graphene.Boolean()


class CreateDroneRewardsProfile(ModelMutation):
    """Mutation for creating a business partner's drone rewards information"""

    drone_rewards_profile = graphene.Field(
        DroneRewardsProfile,
        description="A business partner's drone rewards information.",
    )

    class Arguments:
        input = DroneRewardsCreateInput(
            description="Fields required to define drone rewards information.",
            required=True,
        )

    class Meta:
        description = "Define the drone rewards information for a dealer."
        exclude = []
        model = models.DroneRewardsProfile
        permissions = (AccountPermissions.MANAGE_USERS,)
        error_type_class = BusinessPartnerError
        error_type_field = "business_partner_errors"


class SAPUserProfileCreateInput(graphene.InputObjectType):
    user = graphene.ID()
    date_of_birth = graphene.String()
    is_company_owner = graphene.Boolean()
    middle_name = graphene.String()
    business_partners = graphene.List(of_type=graphene.ID)


class CreateSAPUserProfile(ModelMutation, GetBusinessPartnerMixin):
    """Mutation for creating a user's SAP user profile. If the id argument is passed
    then this mutation updates the existing SAP user profile with that id."""

    sap_user_profile = graphene.Field(
        SAPUserProfile, description="An SAP user profile that was created."
    )

    class Arguments:
        id = graphene.ID()
        input = SAPUserProfileCreateInput(
            description="Fields required to create SAP user profile.", required=True
        )
        business_partner_id = graphene.ID(
            description="ID of a business partner to create address for.",
        )
        sap_bp_code = graphene.String(description="Card code of a business partner.")

    class Meta:
        description = "Create a new SAP user profile."
        exclude = []
        model = models.SAPUserProfile
        permissions = (AccountPermissions.MANAGE_USERS,)
        error_type_class = BusinessPartnerError
        error_type_field = "business_partner_errors"


class MigrateContactInput(graphene.InputObjectType):
    email = graphene.String(required=True)
    first_name = graphene.String()
    last_name = graphene.String()
    date_of_birth = graphene.String()
    middle_name = graphene.String()
    is_company_owner = graphene.Boolean(default=False)


class BulkMigrateContacts(CustomerCreate, GetBusinessPartnerMixin):
    class Arguments:
        input = graphene.List(of_type=MigrateContactInput)

        business_partner_id = graphene.ID(
            description="ID of a business partner to create address for.",
        )
        sap_bp_code = graphene.String(description="Create Address for Card Code")

    class Meta:
        description = "Updates or creates many business partner contacts."
        exclude = ["password"]
        model = models.User
        permissions = (AccountPermissions.MANAGE_USERS,)
        error_type_class = AccountError
        error_type_field = "account_errors"

    @classmethod
    def clean_input(cls, info, instance, data, input_cls=None):
        """This needs to clean the input for the create user mutation. We're using the
        `CustomerCreate` class as a base class to ensure that all of the appropriate
        events/triggers that should occur when a new user is created happen. But since
        the input for this mutation is actually a graphene List as opposed to the
        CustomerInput type, the usual clean input method will fail. Overriding this
        method ensures that we grab the correct input class.
        """
        if not input_cls:
            input_cls = User

        cleaned_input = {}
        for field_name, field_item in input_cls._meta.fields.items():
            if field_name in data:
                value = data[field_name]

                cleaned_input[field_name] = value
        return cleaned_input

    @classmethod
    def perform_mutation(cls, root, info, **data):
        contact_inputs = data.get("input")
        business_partner: models.BusinessPartner = cls.get_business_partner(data, info)
        responses = []

        # Grab all of the users we'll need and organize them by email address
        contact_cache = {}
        contacts = user_models.User.objects.filter(
            email__in=set(contact["email"] for contact in contact_inputs)
        ).prefetch_related("sapuserprofile__business_partners")
        for contact in contacts:
            contact_cache[contact.email] = contact

        for contact in contact_inputs:
            user = contact_cache.get(contact["email"])
            if not user:
                # Create a new user
                create_user_data = {
                    "email": contact["email"],
                    "first_name": contact.get("first_name"),
                    "last_name": contact.get("last_name"),
                }
                response = super().perform_mutation(root, info, input=create_user_data)
                user = response.user
            else:
                # Update an existing user
                cleaned_input = cls.clean_input(info, user, data)
                user = cls.construct_instance(user, cleaned_input)
                cls.clean_instance(info, user)
                cls.save(info, user, cleaned_input)
                cls._save_m2m(info, user, cleaned_input)

            sap_profile, created = models.SAPUserProfile.objects.update_or_create(
                user=user,
                defaults={
                    "date_of_birth": contact.get("date_of_birth"),
                    "is_company_owner": contact.get("is_company_owner", False),
                    "middle_name": contact.get("middle_name"),
                },
            )

            responses.append(sap_profile)

        business_partner.sapuserprofiles.set(responses)

        return cls(**{cls._meta.return_field_name: responses, "errors": []})


class SAPApprovedBrandsInput(graphene.InputObjectType):
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


class AssignApprovedBrands(ModelMutation, GetBusinessPartnerMixin):
    """Mutation for assigning approved brands to a business partner"""

    approved_brands = graphene.Field(
        SAPApprovedBrands, description="The approved brands for this business partner."
    )

    class Arguments:
        business_partner_id = graphene.ID(
            description="ID of a business partner to create address for.",
            required=False,
        )
        sap_bp_code = graphene.String(
            description="SAP card code for the business partner."
        )
        input = SAPApprovedBrandsInput(
            description="List of approved brands to assign.", required=True
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

        business_partner = cls.get_business_partner(data, info)

        # Get or create the approved brands
        try:
            approved_brands = business_partner.approvedbrands
        except models.ApprovedBrands.DoesNotExist:
            approved_brands = models.ApprovedBrands(business_partner=business_partner)

        # Update based on the input
        for brand, value in data["input"].items():
            setattr(approved_brands, brand, value)

        approved_brands.save()

        return cls.success_response(approved_brands)
