import graphene
from typing import TYPE_CHECKING

from django.db.models import Q

from firstech.SAP import models
from saleor.account import models as user_models
from saleor.channel.models import Channel
from saleor.checkout import AddressType
from saleor.core.permissions import AccountPermissions
from saleor.core.tracing import traced_atomic_transaction
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
    SAPApprovedBrands,
    SAPUserProfile,
)
from saleor.shipping.models import ShippingMethod

if TYPE_CHECKING:
    from saleor.plugins.manager import PluginsManager
    from saleor.plugins.sap_orders.plugin import SAPPlugin


def upsert_business_partner(bp: dict) -> models.BusinessPartner:
    """Upserts the business partner from SAP into Saleor.
    :param bp: The dict of business partner information retrieved from the SAP service
        layer.
    :returns: The models.BusinessPartner object
    """
    try:
        channel_id = Channel.objects \
            .values_list("id", flat=True) \
            .get(slug=bp["channel_slug"])
    except Channel.DoesNotExist:
        channel_id = None

    try:
        sales_manager_user_id = models.SAPSalesManager.objects \
            .values_list("id", flat=True) \
            .get(name=bp["U_SalesManager"])
    except models.SAPSalesManager.DoesNotExist:
        sales_manager_user_id = None

    try:
        inside_sales_rep_id = models.SAPSalesManager.objects \
            .values_list("id", flat=True) \
            .get(name=bp["U_SalesSupport"])
    except models.SAPSalesManager.DoesNotExist:
        inside_sales_rep_id = None

    try:
        shipping_method_id = ShippingMethod.objects \
            .values_list("id", flat=True) \
            .get(private_metadata__TrnspCode=bp["ShippingType"])
    except ShippingMethod.DoesNotExist:
        shipping_method_id = None

    sync_partner = True if bp["U_V33_SYNCB2B"] == "YES" else False

    business_partner, _ = models.BusinessPartner.objects.update_or_create(
        sap_bp_code=bp["CardCode"],
        defaults={
            "account_balance": bp["CurrentAccountBalance"],
            "account_is_active": True,  # TODO
            "account_purchasing_restricted": False,  # TODO
            "company_name": bp["CardName"],
            "company_url": bp["Website"],
            "credit_limit": bp["CreditLimit"],
            "customer_type": bp["CompanyPrivate"],
            "debit_limit": bp["MaxCommitment"],
            "inside_sales_rep_id": inside_sales_rep_id,
            "internal_ft_notes": bp["FreeText"],
            "payment_terms": bp["payment_terms"],
            "channel_id": channel_id,
            "sales_manager_id": sales_manager_user_id,
            "shipping_preference_id": shipping_method_id,
            "sync_partner": sync_partner,
            "warranty_preference": bp["U_Warranty"],
        }
    )

    # Get the outside sales rep users from the email addresses we have
    outside_sales_rep_users = list(user_models.User.objects.filter(
        email__in=bp["outside_sales_rep_emails"]
    ))

    business_partner.outside_sales_rep.set(
        outside_sales_rep_users,
        through_defaults={"name": bp["outside_sales_rep_name"]},
        clear=True
    )

    return business_partner


def upsert_business_partner_addresses(bp: dict, business_partner: models.BusinessPartner):
    """ Function for upserting the addresses on an existing business partner. This will
    remove from saleor any addresses that have been removed from SAP. Removing addresses
    this way doesn't delete the addresses from the Address table, it just disassociates
    those addresses from the business partner. So any orders that are pointing to those
    addresses will be unaffected.

    :param bp: A dict of business partner information retrieved from the SAP service
        layer.
    :param business_partner: The existing models.BusinessPartner object that the
        addresses belong to.

    """

    # Get all of the existing BusinessPartnerAddress objects and create a cache
    # of them to avoid querying the database more than we need to
    existing_bp_addresses = models.BusinessPartnerAddresses.objects.filter(
        business_partner=business_partner
    ).prefetch_related("address")

    existing_row_nums = set()
    existing_bp_address_cache = {}
    for existing_address in existing_bp_addresses:
        existing_row_nums.add(existing_address.row_number)
        existing_bp_address_cache[existing_address.row_number] = existing_address

    addresses_to_update = []
    addresses_to_create = []
    for sap_address in bp["BPAddresses"]:
        # check if the row number of the address from SAP matches one in our cache
        # if it does, then we will update an existing Address, otherwise we will
        # create a new Address and BusinessPartnerAddresses object for it.
        if existing_bp_address := existing_bp_address_cache.get(
                sap_address["RowNum"]
        ):
            address = existing_bp_address.address
            addresses_to_update.append(address)
        else:
            # Create a new address model
            address = user_models.Address()
            addresses_to_create.append(address)
            existing_row_nums.add(sap_address["RowNum"])

        update_fields = {
            "company_name": sap_address["AddressName"] or "",
            "street_address_1": sap_address["Street"],
            "street_address_2": sap_address["BuildingFloorRoom"] or "",
            "city": sap_address["City"],
            "country_area": sap_address["State"],
            "country": sap_address["Country"],
            "postal_code": sap_address["ZipCode"] or "",
            "row_number": sap_address["RowNum"],
            "type": AddressType.SHIPPING if sap_address[
                                                "AddressType"] == "bo_ShipTo" else AddressType.BILLING,
        }
        for attribute, value in update_fields.items():
            setattr(address, attribute, value)

    if addresses_to_update:
        fields = list(update_fields.keys())
        # Need to take these out or postgres gets scared
        # (cause they're not real model fields)
        fields.remove("row_number")
        fields.remove("type")
        user_models.Address.objects.bulk_update(
            addresses_to_update, fields=fields
        )

    user_models.Address.objects.bulk_create(addresses_to_create)

    # Remove any BusinessPartnerAddress that we didn't update or create (they don't
    # exist in SAP anymore). This doesn't delete the Address, just detaches it.
    existing_bp_addresses.filter(~Q(row_number__in=existing_row_nums)).delete()

    # Create the new BusinessPartnerAddresses objects for new addresses (this is
    # why we needed to add the row_number and type attributes to the Address object)
    bp_addresses_to_create = []
    for new_address in addresses_to_create:
        bp_addresses_to_create.append(
            models.BusinessPartnerAddresses(
                business_partner=business_partner,
                address=new_address,
                row_number=new_address.row_number,
                type=new_address.type
            )
        )

    models.BusinessPartnerAddresses.objects.bulk_create(bp_addresses_to_create)


def upsert_business_partner_contacts(bp: dict, business_partner: models.BusinessPartner):
    """Function for upserting the contacts of an existing business partner. Will create
    or update User models for each SAP contact. If any contacts have been removed from
    SAP, those users will be detached from the business partner in Saleor, but the
    User itself will not be deleted."""

    # Get all existing contacts we have for this business partner in Saleor already
    # and organize into a cache by email address
    existing_bp_contacts = user_models.User.objects.filter(
        sapuserprofile__business_partners=business_partner
    )
    contact_cache = {}
    for existing_bp_contact in existing_bp_contacts:
        contact_cache[existing_bp_contact.email] = existing_bp_contact

    # Prepare the updates from the SAP data
    contacts_to_update = []
    for sap_contact in bp["ContactEmployees"]:
        normalized_email = user_models.UserManager.normalize_email(
            sap_contact["E_Mail"]
        )
        if not normalized_email:
            # Contacts in SAP don't necessarily have an email address
            continue

        if contact := contact_cache.get(normalized_email):
            contacts_to_update.append(contact)
        else:
            # It's possible that the user already exists, but it's not attached
            # to the business partner.
            contact, _ = user_models.User.objects.get_or_create(
                email=normalized_email
            )
            contacts_to_update.append(contact)
            # Make sure we have an sap user profile (new users won't)
            if not hasattr(contact, "sapuserprofile"):
                models.SAPUserProfile.objects.create(user=contact)

        update_user_fields = {
            "first_name": sap_contact["FirstName"] or "",
            "last_name": sap_contact["LastName"] or ""
        }
        for attribute, value in update_user_fields.items():
            setattr(contact, attribute, value)

        update_sap_profile_fields = {
            "middle_name": sap_contact["MiddleName"],
            "date_of_birth": sap_contact["DateOfBirth"],
            "is_company_owner": False,  # TODO where does this come from??
        }
        for attribute, value in update_sap_profile_fields.items():
            setattr(contact.sapuserprofile, attribute, value)

    # Update any changes to pre-existing users
    if contacts_to_update:
        user_models.User.objects.bulk_update(
            contacts_to_update, fields=list(update_user_fields.keys())
        )

        models.SAPUserProfile.objects.bulk_update(
            [contact.sapuserprofile for contact in contacts_to_update],
            fields=list(update_sap_profile_fields.keys())
        )

    # Detach any other users that are connected to this business partner that were
    # not included in the update or creation process. They have been removed from
    # this business partner in SAP.
    business_partner.sapuserprofiles.set(
        [contact.sapuserprofile for contact in contacts_to_update],
        clear=True
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


class UpsertBusinessPartner(ModelMutation, GetBusinessPartnerMixin):
    """Mutation for upserting a business partner from SAP. This mutation will also
    upsert any addresses and contacts for the business partner. Information for the
    business partner will be retrieved from the SAP service layer using the SAP plugin.
    """

    business_partner = graphene.Field(
        BusinessPartner, description="The business partner instance that was upserted."
    )

    class Arguments:
        sap_bp_code = graphene.String(
            description="SAP Card code of a business partner."
        )

    class Meta:
        description = "Upsert an SAP business partner inside Saleor."
        exclude = []
        model = models.BusinessPartner
        permissions = (AccountPermissions.MANAGE_USERS,)
        error_type_class = BusinessPartnerError
        error_type_field = "business_partner_errors"

    @classmethod
    @traced_atomic_transaction()
    def perform_mutation(cls, _root, info, **data):
        manager: PluginsManager = info.context.plugins
        sap_plugin: SAPPlugin = manager.get_plugin(plugin_id="firstech.sap")
        if not sap_plugin:
            # the SAP plugin is inactive or doesn't exist
            return

        bp = sap_plugin.fetch_business_partner(data["sap_bp_code"])

        # These three tasks have been broken up into separate functions to try and keep
        # this organized.
        business_partner = upsert_business_partner(bp)
        upsert_business_partner_addresses(bp, business_partner)
        upsert_business_partner_contacts(bp, business_partner)

        return cls.success_response(business_partner)


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
