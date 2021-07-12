import decimal

import graphene
from typing import Optional, Tuple, List

from django.core.exceptions import ValidationError
from django.utils.text import slugify

import saleor.product.models as product_models

from firstech.SAP import models
from saleor.account import models as user_models
from saleor.checkout import AddressType
from saleor.core.permissions import (
    AccountPermissions, ChannelPermissions,
    ProductPermissions, OrderPermissions,
)
from saleor.graphql.account.enums import AddressTypeEnum
from saleor.graphql.account.mutations.staff import CustomerCreate
from saleor.graphql.account.types import AddressInput, User
from saleor.graphql.attribute.utils import AttributeAssignmentMixin
from saleor.graphql.channel import ChannelContext
from saleor.graphql.core.mutations import ModelMutation, BaseMutation
from saleor.graphql.core.scalars import Decimal, PositiveDecimal
from saleor.graphql.core.types.common import AccountError, OrderError
from saleor.graphql.order.mutations.draft_orders import (
    DraftOrderInput,
    DraftOrderUpdate,
    DraftOrderComplete,
)
from saleor.graphql.order.mutations.orders import (
    OrderLineDelete,
    OrderLinesCreate,
    OrderLineUpdate,
)
from saleor.graphql.SAP.enums import DistributionTypeEnum
from saleor.graphql.SAP.types import (
    BusinessPartnerError,
    BusinessPartner,
    SAPUserProfile,
    SAPApprovedBrands,
    DroneRewardsProfile,
    SAPProductError,
)
from saleor.graphql.product.bulk_mutations.products import ProductVariantStocksUpdate
from saleor.graphql.product.mutations.channels import (
    ProductChannelListingUpdate,
    ProductVariantChannelListingUpdate,
)
from saleor.graphql.product.mutations.products import ProductVariantCreate
from saleor.graphql.product.types import ProductVariant
from saleor.order import models as order_models
from saleor.order.utils import get_valid_shipping_methods_for_order
from saleor.warehouse.models import Warehouse


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
                only_type=BusinessPartner
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
    outside_sales_rep = graphene.String()
    outside_sales_rep_emails = graphene.List(of_type=graphene.String)
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
        BusinessPartner,
        description="A business partner instance that was created."
    )

    class Arguments:
        business_partner_id = graphene.ID(
            description="ID of an existing business partner to update.",
        )
        sap_bp_code = graphene.String(
            description="SAP Card code of an existing business partner to update."
        )
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

        return cleaned_input


class BusinessPartnerAddressCreate(ModelMutation, GetBusinessPartnerMixin):
    business_partner = graphene.Field(
        BusinessPartner,
        description="A business partner instance for which the address was created."
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
            businesspartneraddresses__type=address_type
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
                address_id=instance.id
            )
            response.business_partner = business_partner
            # If this BP doesn't have default billing or shipping addresses, set them
            if address_type:
                if (
                    address_type == AddressType.BILLING and
                    not business_partner.default_billing_address
                ):
                    business_partner.default_billing_address = response.address
                elif (
                    address_type == AddressType.SHIPPING and
                    not business_partner.default_shipping_address
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

        existing_addresses = set(models.BusinessPartnerAddresses.objects.filter(
            business_partner=business_partner
        ).values_list("address__company_name", "type"))

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
        description="A business partner's drone rewards information."
    )

    class Arguments:
        input = DroneRewardsCreateInput(
            description="Fields required to define drone rewards information.",
            required=True
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
        SAPUserProfile,
        description="An SAP user profile that was created."
    )

    class Arguments:
        id = graphene.ID()
        input = SAPUserProfileCreateInput(
            description="Fields required to create SAP user profile.",
            required=True
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
        """ This needs to clean the input for the create user mutation. We're using the
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
                    "last_name": contact.get("last_name")
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
                }
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
        SAPApprovedBrands,
        description="The approved brands for this business partner."
    )

    class Arguments:
        business_partner_id = graphene.ID(
            description="ID of a business partner to create address for.",
            required=False
        )
        sap_bp_code = graphene.String(
            description="SAP card code for the business partner."
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

        business_partner = cls.get_business_partner(data, info)

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


class SAPProductMetadata(graphene.InputObjectType):
    inventory_uom = graphene.String(description="Value from SAP field `OITM.InvntryUom`.")
    manufacture = graphene.String(description="Value from SAP field `OITM.CardCode`.")
    on_hold = graphene.Int(description="Value from SAP field `OITM.OnHldPert`.")
    on_limited_hold = graphene.Int(description="Value from SAP field `OITM.onHldLimt`.")
    reserved_qty = graphene.Int(description="Value from SAP field `OITW.IsCommited`.")
    website_code = graphene.String(description="Value from SAP field `OITM.U_website_code`.")


class SAPVariantMetadata(graphene.InputObjectType):
    bar_code = graphene.String(description="Value from SAP field `OITM.CodeBars`.")


class SAPProductPrivateMetadata(graphene.InputObjectType):
    last_eval_price = graphene.String(description="Value from SAP field `OITM.LstEvlPric`.")
    last_purchase_price = graphene.String(description="Value from SAP field `OITM.LastPurPrc`.")
    last_updated = graphene.String(description="Value from SAP field `OITM.UpdateDate`.")
    retail_taxable = graphene.String(description="Value from SAP field `OITM.RetilrTax`.")
    wholesale_taxable = graphene.String(description="Value from SAP field `OITM.WholSlsTax`.")
    com_level = graphene.String(description="Value from SAP field `OITM.U_V33_COMLEVEL`.")
    synced = graphene.String(description="Value from SAP field `OITM.U_sync`.")


class SAPVariantPrivateMetadata(graphene.InputObjectType):
    on_order_with_vendor = graphene.Int(description="Value from SAP field `OITW.OnOrder`.")
    best_buy_sku = graphene.String(description="Value from SAP field `OITM.U_V33_BESTBUYSKU`.")


class SAPProductPriceList(graphene.InputObjectType):
    name = graphene.String(
        description="Value from SAP field `OPLN.ListName` (will be converted to a standard slug for comparison internally with Channels).",
        required=True,
    )
    price = PositiveDecimal(
        description="Value from SAP field `ITM1.Price`.",
        required=True,
    )


class SAPWarehouseStock(graphene.InputObjectType):
    warehouse_id = graphene.String(
        description="Value from SAP field `OITW.WhsCode`.",
        required=True,
    )
    quantity = graphene.Int(
        description="Value from SAP field calculation of `OITW.OnHand - OITW.IsCommitted`.",
        required=True,
    )


class SAPProductInput(graphene.InputObjectType):
    sku = graphene.String(required=True, description="Value from SAP field `OITM.ItemCode`.")
    brand_name = graphene.String(description="Value from SAP field `OITM.U_BrandName`.")
    metadata = graphene.Field(
        SAPProductMetadata,
        description="Public metadata values associated with this product.",
    )
    private_metadata = graphene.Field(
        SAPProductPrivateMetadata,
        description="Private metadata values associated with this product.",
    )
    variant_metadata = graphene.Field(
        SAPVariantMetadata,
        description="Public metadata values associated with this product variant."
    )
    variant_private_metadata = graphene.Field(
        SAPVariantPrivateMetadata,
        description="Private metadata values associated with this product variant."
    )
    price_lists = graphene.List(
        graphene.NonNull(SAPProductPriceList),
        description="Price list information for this product. Will be converted into existing Channels.",
        required=True,
    )
    stocks = graphene.List(
        graphene.NonNull(SAPWarehouseStock),
        description="Warehouse stock information for this product."
    )


def round_money(value: Optional[decimal.Decimal]) -> Optional[decimal.Decimal]:
    """Ensure money value is a Decimal to two points of precision."""
    if value is None:
        return None
    if not isinstance(value, decimal.Decimal):
        value = decimal.Decimal(value)
    return value.quantize(decimal.Decimal(".01"), decimal.ROUND_HALF_UP)


class UpsertSAPProduct(BaseMutation):
    """Mutation for performing a synchronization between SAP and Saleor

    This can technically be handled through GraphQL, but SAP's Integration Framework
    doesn't provide nearly flexible enough tools so it's much easier to just have it
    push the information to Python and then figure things out on this end.
    """
    product_variant = graphene.Field(
        ProductVariant, description="The upserted product's details."
    )

    class Arguments:
        product_type = graphene.ID(
            description="ID of the product type for this product; must be set before SAP will upsert the product but isn't technically used for updates because product types cannot be changed after the fact.",
            required=True
        )
        input = SAPProductInput(required=True)

    class Meta:
        description = "Upsert a product from SAP into Saleor."
        permissions = (
            ChannelPermissions.MANAGE_CHANNELS,
            ProductPermissions.MANAGE_PRODUCTS,
        )
        error_type_class = SAPProductError
        error_type_field = "sap_product_errors"

    @classmethod
    def perform_mutation(cls, root, info, **data):
        in_data = data.get("input", {})
        sku = in_data.get("sku")
        variant = product_models.ProductVariant.objects.filter(sku=sku).first()
        product_type = cls.get_node_or_error(info, data.get('product_type'))
        if not variant:
            # Check if we already have a base product type when working with variants
            existing_product = None
            if product_type.has_variants:
                for base_product in product_models.Product.objects.filter(
                    product_type=product_type
                ).all():
                    # To determine if this is the base product, we compare its default
                    #  variant's base SKU with our current base SKU (currently all
                    #  products with variants in the store use the pattern `BASE-SIZE`)
                    # TODO: this is pretty fragile; should we store base SKU in metadata?
                    if (
                        base_product.default_variant
                        and base_product.default_variant.sku.split('-')[:-1] == sku.split('-')[:-1]
                    ):
                        existing_product = base_product
                        break
            # Create our base product, if necessary
            if existing_product:
                product = existing_product
            else:
                # Create our base product
                product = product_models.Product()
                product.product_type = product_type
                product.name = sku
                product.slug = slugify(sku)
                uncategorized = product_models.Category.objects.filter(
                    slug="uncategorized"
                ).first()
                product.category = uncategorized
                product.save()
            # Create our product variant (will get saved later)
            variant = product_models.ProductVariant()
            variant.product = product
            variant.sku = sku
        else:
            product = variant.product
        # Populate the brand name attribute
        if in_data.get("brand_name"):
            attributes_qs = product_type.product_attributes
            # Saleor's specified types are flat-out wrong for this method, so...
            # noinspection PyTypeChecker
            attributes = AttributeAssignmentMixin.clean_input(
                [{
                    "slug": "brand-name",
                    "values": [in_data["brand_name"]],
                }],
                attributes_qs,
                is_variant=False,
            )
            AttributeAssignmentMixin.save(product, attributes)
        # Populate the public metadata for the product
        metadata = {
            key: value for key, value in in_data.get("metadata", {}).items()
        }
        if metadata:
            product.store_value_in_metadata(items=metadata)
            product.save(update_fields=["metadata"])
        private_metadata = {
            key: value for key, value in in_data.get("private_metadata", {}).items()
        }
        if private_metadata:
            product.store_value_in_private_metadata(items=private_metadata)
            product.save(update_fields=["private_metadata"])

        # Save our information for the variant; using the native save for this because
        #  it has some related events that I don't want to mess with
        ProductVariantCreate.save(info, variant, {})
        # Now that we have a variant, update our stock information
        warehouses = []
        if in_data.get("stocks"):
            # Map our SAP IDs to Saleor IDs
            for warehouse_data in in_data["stocks"]:
                warehouse = Warehouse.objects.filter(
                    metadata__contains={"warehouse_id": warehouse_data["warehouse_id"]}
                ).first()
                if warehouse:
                    warehouses.append(warehouse)
        if warehouses:
            ProductVariantStocksUpdate.update_or_create_variant_stocks(
                variant, in_data["stocks"], warehouses
            )
        # Add size attribute, if we have it for this product
        if product_type.has_variants and product_type.variant_attributes:
            attributes_qs = product_type.variant_attributes
            # Saleor's specified types are flat-out wrong for this method, so...
            # noinspection PyTypeChecker
            attributes = AttributeAssignmentMixin.clean_input(
                [{
                    "slug": "size",
                    "values": [sku.split("-")[-1]],
                }],
                attributes_qs,
                is_variant=True,
            )
            AttributeAssignmentMixin.save(variant, attributes)
        # Update the variant metadata
        variant_metadata = {
            key: value for key, value in in_data.get("variant_metadata", {}).items()
        }
        if variant_metadata:
            variant.store_value_in_metadata(items=variant_metadata)
            variant.save(update_fields=["metadata"])
        variant_private_metadata = {
            key: value for key, value in in_data.get("variant_private_metadata", {}).items()
        }
        if variant_private_metadata:
            variant.store_value_in_private_metadata(items=variant_private_metadata)
            variant.save(update_fields=["private_metadata"])

        # Look up all channels
        channel_slugs = set()
        for price_list in in_data["price_lists"]:
            price_list["slug"] = slugify(price_list["name"])
            channel_slugs.add(price_list["slug"])
        channel_map = {
            x.slug: x
            for x in product_models.Channel.objects.filter(slug__in=channel_slugs).all()
        }
        # Make sure that our price lists are attached to the product
        update_channels = []
        for price_list in in_data["price_lists"]:
            # We only support price lists that are already defined in Saleor, so check
            #  for a pre-existing channel
            channel = channel_map.get(price_list["slug"])
            if not channel:
                continue
            update_channels.append({
                "channel": channel,
            })
        if update_channels:
            ProductChannelListingUpdate.update_channels(
                product, update_channels=update_channels
            )
        # And then adjust the prices for the variant in those channels
        price_updates = []
        for price_list in in_data["price_lists"]:
            # Just like products, we only use pre-defined channels
            channel = channel_map.get(price_list["slug"])
            if not channel:
                continue
            price_updates.append({
                "channel": channel,
                "price": round_money(price_list["price"]),
            })
        if price_updates:
            ProductVariantChannelListingUpdate.save(info, variant, price_updates)

        return cls(
            product_variant=ChannelContext(node=variant, channel_slug=None),
            errors=[],
        )


class SAPLineItemInput(graphene.InputObjectType):
    sku = graphene.String()
    quantity = graphene.Int()


class SAPOrderMetadataInput(graphene.InputObjectType):
    due_date = graphene.String(description="Expected shipping date. From ORDR.DocDueDate")
    date_shipped = graphene.String(description="From ORDR.ShipDate")
    payment_method = graphene.String(description="From ORDR.PaymentMethod")
    PO_number = graphene.String(description="From ORDR.ImportFileNum")


class SAPOrderInput(graphene.InputObjectType):
    draft_order_input = DraftOrderInput(
        required=True,
        description="Fields required to create an order."
    )
    lines = graphene.List(
        of_type=SAPLineItemInput,
        description="List of order line items"
    )
    metadata = graphene.Field(
        SAPOrderMetadataInput,
        description="Additional SAP information can be stored as metadata."
    )


class UpsertSAPOrder(DraftOrderUpdate):
    """For syncing sales orders in SAP to orders in Saleor. See the docstring in the
    methods below for details on the billing and shipping address inputs.
    """
    class Arguments:
        input = SAPOrderInput(
            required=True,
            description="Input data for upserting a draft order from SAP."
        )
        doc_entry = graphene.String(
            required=True,
            description="The DocEntry value from SAP (primary key for SAP orders)."
        )
        # We need to keep card code and doc_entry together because for some reason
        # doc_entry numbers are only unique to the business partner.
        sap_bp_code = graphene.String(
            required=True,
            description="The SAP CardCode for the order."
        )
        confirm_order = graphene.Boolean(
            required=False,
            default_value=False,
            description="Whether or not to attempt to confirm this order automatically."
        )
        shipping_method_name = graphene.String(
            description="Name of the shipping method to use."
        )
        channel_name = graphene.String(description="Name of the channel to use.")
        shipping_address = graphene.String(description="Semicolon delimited address.")
        billing_address = graphene.String(description="Semicolon delimited address.")

    class Meta:
        description = "Creates or updates a draft order."
        model = order_models.Order
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def get_instance(cls, info, **data):
        instance = order_models.Order.objects.filter(
            metadata__doc_entry=data["doc_entry"],
            metadata__sap_bp_code=data["sap_bp_code"]
        ).prefetch_related("lines").first()

        if not instance:
            instance = cls._meta.model()

        return instance

    @staticmethod
    def parse_address_etc(city_state_zip: str, country: str) -> Tuple[str, str, str]:
        """This function takes part of an address line that has the city, state and zip
        in it and splits them up into those pieces. Assumes that the last word is the
        zip, the next to last word is the state abbreviation, and the remaining words.

        The country is also needed as an input because canadian postal codes are two
        words.

        are the city. Example:
        "Lake Forest Park WA 98765" -> "Lake Forest Park", "WA", "98765"
        """
        words = city_state_zip.split()
        postal_code = words.pop()

        # Canadian postal codes are two words
        if country == "CA":
            postal_code = words.pop() + " " + postal_code

        state = words.pop()
        city = " ".join(words)
        return city, state, postal_code

    @staticmethod
    def parse_country(country: str) -> str:
        # Most likely the country will come from SAP as either "USA" or "Canada",
        # but it's possible for an SAP user to manually enter an address so I'm being
        # as forgiving as possible with spellings
        if country.upper() in (
                "USA", "US", "UNITED STATES", "UNITED STATES OF AMERICA"
        ):
            return "US"
        elif country.upper() in ("CANADA", "CA"):
            return "CA"
        else:
            raise ValidationError("Country not recognized")

    @classmethod
    def parse_address_string(cls, address_string):
        """<rant> Because of what can happen on the SAP side, getting the shipping and
        billing addresses from a sales order is a real mess. Ideally the integration
        framework would be able to include the billing/shipping addresses inside the
        DraftOrderInput type. However, when we pull the address from the database it's
        normalized and we have to parse out street1, street2, city, state, zip, country
        manually. We can do a little bit of that on the SQL side by replacing linebreaks
        with a `;`. Unfortunately the city, state, and zip code are all on one line. And
        then there's no good way to break those pieces up inside the integration
        framework because we can't figure out how to get the javascript plug-in working,
        and God only knows how to do that with xslt/xpath. And of course there are some
        subtle differences in how US and Canadian addresses work. So instead we send it
        over as a string, then we do the rest of the address parsing here in python
        land, and then finally stuff everything back into the DraftOrderInput.</rant>

        Example inputs for US address:
            123 Fake St.;Unit A;Townsville NY 12345;USA
            742 Evergreen Terrace;;Springfield OR 98123;USA

        Example input for CA address:
            3213 Curling Lane Apt. C;Vancouver BC V1E 4X3;CANADA
        """
        address_lines: List = address_string.split(";")
        # The last line is always the country
        country = cls.parse_country(address_lines.pop())

        # The next to last line contains the city, state (or province), and postal code
        city, state, postal_code = cls.parse_address_etc(
            address_lines.pop(),
            country
        )

        # The remaining 1 or 2 lines (US addresses should have 2 lines, CA should only
        # have 1)
        line_1 = address_lines[0]

        # In the event we have more than 2 extra address lines, we'll just concatenate
        # them into one big line
        if len(address_lines) >= 2:
            line_2 = " ".join(address_lines[1:])
        else:
            line_2 = None

        return {
            "street_address_1": line_1,
            "street_address_2": line_2,
            "city": city,
            "country_area": state,
            "country": country,
            "postal_code": postal_code
        }

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        # Get the order instance
        order: order_models.Order = cls.get_instance(info, **data)
        new_order = False if order.pk else True
        input: dict = data["input"]
        draft_order_input = input["draft_order_input"]
        channel_name = data.get("channel_name")
        shipping_method_name = data.get("shipping_method_name")

        if shipping_address := data.get("shipping_address"):
            draft_order_input["shipping_address"] = cls.parse_address_string(
                shipping_address)

        if billing_address := data.get("billing_address"):
            draft_order_input["billing_address"] = cls.parse_address_string(
                billing_address)

        # Get the channel model object from the channel name
        if channel_name:
            channel = product_models.Channel.objects.get(slug=slugify(channel_name))
            draft_order_input["channel_id"] = graphene.Node.to_global_id(
                "Channel",
                channel.id
            )

        # Form the line items for the order
        if lines := input.get("lines", []):
            # We need to translate SKU into variant ids.
            # Sort our line items by SKU
            lines = sorted(lines, key=lambda line: line["sku"])

            # Get all the product variants for the SKUs provided (also sorted by SKU)
            product_variants: List[dict] = list(product_models.ProductVariant.objects.filter(
                sku__in=[line["sku"] for line in lines]
            ).values("id", "sku").order_by("sku"))

            # Replace each line item's SKU key-value pair with variant's global id
            # There is a possibility that there are SKUs from SAP that don't exist in
            # Saleor, so we will raise a validation error if any exist
            i = 0
            bad_line_items = []
            num_product_variants = len(product_variants)
            for sap_line in lines:
                if (
                        i < num_product_variants and
                        sap_line["sku"] == product_variants[i]["sku"]
                ):
                    sap_line["variant_id"] = graphene.Node.to_global_id(
                        "ProductVariant",
                        product_variants[i]["id"]
                    )
                    del sap_line["sku"]
                    i += 1
                else:
                    bad_line_items.append(sap_line["sku"])

            if bad_line_items:
                raise ValidationError(
                    f"The following SKUs do not exist in Saleor: {bad_line_items}"
                )

        metadata = input.get("metadata", {})
        # Keep SAP's DocEntry field and business partner code in the meta data
        # so we can refer to this order again
        metadata.update({
            "doc_entry": data["doc_entry"],
            "sap_bp_code": data["sap_bp_code"]
        })

        # If this is a new order then we can use the draftOrderCreate mutation which
        # takes the lines argument. Otherwise for an update we can't include lines
        if new_order:
            draft_order_input["lines"] = lines
        else:
            # Channel id can't be changed
            del draft_order_input["channel_id"]

        # Update the draft Order
        # Ok...so. We can't use cls.clean_input for this because we would need to be
        # able to pass in the `input_cls` argument to make sure the
        # BaseMutation.clean_input method is referring to the right input class.
        # (We want to clean theDraftOrderCreateInput not the SAPOrderInput).
        # But the DraftOrderUpdate class doesn't pass the `input_cls` argument through
        # to the BaseMutation class. So we either need to edit the stock saleor code to
        # pass that argument through OR explicitly call a fresh DraftOrderUpdate class
        # to make sure the right input class gets used.
        cleaned_input = DraftOrderUpdate.clean_input(info, order, draft_order_input)
        order = cls.construct_instance(order, cleaned_input)
        cls.clean_instance(info, order)
        cls.save(info, order, cleaned_input)
        cls._save_m2m(info, order, cleaned_input)
        cls.post_save_action(info, order, cleaned_input)

        # Attach our metadata
        if metadata:
            order.store_value_in_private_metadata(items=metadata)
            order.save(update_fields=["private_metadata"])

        # For existing orders we must update any changes to line items that were made
        if not new_order:
            existing_lines = order_models.OrderLine.objects.filter(
                order_id=order.id
            ).all()
            line_cache = {}
            for line in existing_lines:
                line_cache[
                    graphene.Node.to_global_id("ProductVariant", line.variant_id)
                ] = line

            lines_to_create = []
            for line in lines:
                if existing_line := line_cache.pop(line["variant_id"], None):
                    if existing_line.quantity != line["quantity"]:
                        # We need to update the qty. There's a bunch of special behind
                        # the scenes actions that take place in the normal update order
                        # mutation. Instead of trying to recreate that all we'll just
                        # call that mutation from here.
                        OrderLineUpdate.perform_mutation(
                            _root,
                            info,
                            id=graphene.Node.to_global_id(
                                "OrderLine",
                                existing_line.id
                            ),
                            input={"quantity": line["quantity"]}
                        )
                else:
                    lines_to_create.append(line)

            # Create the new lines using the mutation for that
            OrderLinesCreate.perform_mutation(
                _root,
                info,
                id=graphene.Node.to_global_id("Order", order.id),
                input=lines_to_create
            )

            # Delete any remaining lines that weren't updated or added
            for variant_id, line in line_cache.items():
                OrderLineDelete.perform_mutation(
                    _root,
                    info,
                    id=graphene.Node.to_global_id("OrderLine", line.id)
                )

        # Lookup the shipping method by name and update the order
        if shipping_method_name:
            available_shipping_methods = get_valid_shipping_methods_for_order(order)
            shipping_method = available_shipping_methods.filter(
                private_metadata__TrnspName=shipping_method_name
            ).first()
            order.shipping_method = shipping_method
            order.shipping_method_name = shipping_method.name
            order.save()

        if input.get("confirm_order", False):
            # Try to move this draft order to confirmed
            try:
                DraftOrderComplete.perform_mutation(
                    _root,
                    info,
                    graphene.Node.to_global_id("Order", order.id)
                )
            except ValidationError:
                # If there is not enough stock available for the order, confirmation
                # will fail.
                pass

        return cls.success_response(order)
