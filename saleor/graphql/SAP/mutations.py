import graphene
from slugify import slugify

import saleor.product.models as product_models

from firstech.SAP import models
from saleor.checkout import AddressType
from saleor.core.permissions import (
    AccountPermissions, ChannelPermissions,
    ProductPermissions,
)
from saleor.graphql.account.enums import AddressTypeEnum
from saleor.graphql.account.types import AddressInput
from saleor.graphql.attribute.utils import AttributeAssignmentMixin
from saleor.graphql.channel import ChannelContext
from saleor.graphql.core.mutations import ModelMutation, BaseMutation
from saleor.graphql.core.scalars import Decimal
from saleor.graphql.core.types.common import AccountError
from saleor.graphql.SAP.enums import DistributionTypeEnum
from saleor.graphql.SAP.types import (
    BusinessPartnerError,
    BusinessPartner,
    SAPUserProfile,
    SAPApprovedBrands,
    DroneRewardsProfile,
    SAPProductError,
)
from saleor.graphql.product.mutations.products import ProductVariantCreate
from saleor.graphql.product.types import ProductVariant
from saleor.warehouse.models import Warehouse


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
    inside_sales_rep = graphene.String()
    internal_ft_notes = graphene.String()
    outside_sales_rep = graphene.String()
    outside_sales_rep_emails = graphene.List(of_type=graphene.String)
    payment_terms = graphene.String()
    channel = graphene.ID(required=True)
    sales_manager = graphene.String()
    sap_bp_code = graphene.String()
    shipping_preference = graphene.String()
    sync_partner = graphene.Boolean()
    warranty_preference = graphene.String()


class MigrateBusinessPartner(ModelMutation):
    """Mutation for creating (i.e. migrating over) a business partner from SAP. If the
    id argument is passed, then this will update the existing business partner with that
    id."""
    business_partner = graphene.Field(
        BusinessPartner,
        description="A business partner instance that was created."
    )

    class Arguments:
        id = graphene.ID()
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

        object_id = data.get("id")
        qs = data.get("qs")
        card_code = data.get("input", {}).get("card_code")
        if object_id:
            model_type = cls.get_type_for_model()
            instance = cls.get_node_or_error(
                info, object_id, only_type=model_type, qs=qs
            )
        elif card_code:
            try:
                instance = models.BusinessPartner.objects.get(card_code=card_code)
            except models.BusinessPartner.DoesNotExist:
                instance = cls._meta.model()
        else:
            instance = cls._meta.model()

        return instance


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
    business_partner = graphene.ID()


class CreateSAPUserProfile(ModelMutation):
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
    price = Decimal(
        description="Value from SAP field `ITM1.Price`.",
        required=True,
    )
    is_published = graphene.Boolean(
        description="Whether this product should be visible in this price list.",
        default=False,
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
    )
    stocks = graphene.List(
        graphene.NonNull(SAPWarehouseStock),
        description="Warehouse stock information for this product."
    )


class UpsertSAPProduct(BaseMutation):
    """Mutation for performing a synchronization between SAP and Saleor

    This can technically be handled through GraphQL, but SAP's Integration Framework
    doesn't provide nearly flexible enough tools so it's much easier to just have it
    push the information to Python and then figure things out on this end.
    """
    product_variant = graphene.Field(ProductVariant, description="The upserted product's details.")

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
        #  it has a bunch of related events and things
        clean_info = {}
        # Try building out our stock information, if we have it
        stocks = []
        if in_data.get("stocks"):
            # Map our SAP IDs to Saleor IDs
            for warehouse_data in in_data["stocks"]:
                warehouse = Warehouse.objects.filter(
                    metadata__contains={"warehouse_id": warehouse_data["warehouse_id"]}
                ).first()
                if warehouse:
                    stocks.append({
                        "warehouse": warehouse.id,
                        "quantity": warehouse_data["quantity"],
                    })
        if stocks:
            clean_info["stocks"] = stocks
        ProductVariantCreate.save(info, variant, clean_info)
        # Add size attribute, if we have it for this product
        if product_type.has_variants and product_type.variant_attributes:
            attributes_qs = product_type.variant_attributes
            # Saleor's specified types are flat-out wrong for this method, so...
            # noinspection PyTypeChecker
            attributes = AttributeAssignmentMixin.clean_input(
                [{
                    "slug": "size",
                    "values": [sku.split("-")[-1:]],
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

        # TODO: update channels for both product and the variant.
        return cls(
            product_variant=ChannelContext(node=variant, channel_slug=None),
            errors=[],
        )
