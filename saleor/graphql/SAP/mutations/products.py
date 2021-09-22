import decimal
from typing import Optional, TYPE_CHECKING

import graphene
from django.utils.text import slugify

import saleor.product.models as product_models
from saleor.core.permissions import (
    ChannelPermissions,
    ProductPermissions,
)
from saleor.graphql.attribute.utils import AttributeAssignmentMixin
from saleor.graphql.channel import ChannelContext
from saleor.graphql.core.mutations import BaseMutation
from saleor.graphql.product.bulk_mutations.products import ProductVariantStocksUpdate
from saleor.graphql.product.mutations.channels import (
    ProductChannelListingUpdate,
    ProductVariantChannelListingUpdate,
)
from saleor.graphql.product.mutations.products import ProductVariantCreate
from saleor.graphql.product.types import ProductVariant
from saleor.graphql.SAP.types import (
    SAPProductError,
)

from saleor.warehouse.models import Warehouse, Stock

if TYPE_CHECKING:
    from saleor.plugins.manager import PluginsManager
    from saleor.plugins.sap_orders.plugin import SAPPlugin


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
        sku = graphene.String(
            description="SKU of the product to upsert.",
            required=True,
        )

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
        manager: PluginsManager = info.context.plugins
        sap_plugin: SAPPlugin = manager.get_plugin(plugin_id="firstech.sap")
        if not sap_plugin:
            # the SAP plugin is inactive or doesn't exist
            return

        sap_product = sap_plugin.fetch_product(data["sku"])

        sku = data["sku"]
        variant = product_models.ProductVariant.objects.filter(sku=sku).first()
        product_type = cls.get_node_or_error(info, sap_product.get("U_product_type"))
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
                        and base_product.default_variant.sku.split("-")[:-1]
                        == sku.split("-")[:-1]
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
        if sap_product.get("U_BrandName"):
            attributes_qs = product_type.product_attributes
            # Saleor's specified types are flat-out wrong for this method, so...
            # noinspection PyTypeChecker
            attributes = AttributeAssignmentMixin.clean_input(
                [
                    {
                        "slug": "brand-name",
                        "values": [sap_product["U_BrandName"]],
                    }
                ],
                attributes_qs,
                is_variant=False,
            )
            AttributeAssignmentMixin.save(product, attributes)
        # Populate the public metadata for the product
        metadata = {
            "inventoryUom": sap_product.get("InventoryUOM", "") or "",
            "manufacture": sap_product.get("Mainsupplier", "") or "",
            "onHold": sap_product.get("CapitalGoodsOnHoldPercent", "") or "",
            "onLimitedHold": sap_product.get("CapitalGoodsOnHoldLimit", "") or "",
            "reservedQty": sap_product.get("QuantityOrderedByCustomers", "") or "",
            "websiteCode": sap_product.get("U_website_code", "") or "",
        }
        if metadata:
            product.store_value_in_metadata(items=metadata)
            product.save(update_fields=["metadata"])

        # TODO: We are not sure how to get the "x" data fields using the service layer.
        #  They can be retrieved from the database, but aren't exposed otherwise.
        private_metadata = {
            "lastEvalPrice": sap_product.get("x", "") or "",
            "lastPurchasePrice": sap_product.get("x", "") or "",
            "lastUpdated": sap_product.get("UpdateDate", "") or "",
            "retailTaxable": sap_product.get("x", "") or "",
            "wholesaleTaxable": sap_product.get("x", "") or "",
            "comLevel": sap_product.get("U_V33_COMLEVEL", "") or "",
            "synced": sap_product.get("U_sync", "") or "",
        }
        if private_metadata:
            product.store_value_in_private_metadata(items=private_metadata)
            product.save(update_fields=["private_metadata"])

        # Save our information for the variant; using the native save for this because
        #  it has some related events that I don't want to mess with
        ProductVariantCreate.save(info, variant, {})
        # Now that we have a variant, update our stock information
        warehouses = []
        stock_data = []
        if sap_product.get("ItemWarehouseInfoCollection"):
            # Map our SAP IDs to Saleor IDs
            for warehouse_data in sap_product["ItemWarehouseInfoCollection"]:
                warehouse = Warehouse.objects.filter(
                    metadata__contains={"warehouse_id": warehouse_data["WarehouseCode"]}
                ).first()
                if warehouse:
                    warehouses.append(warehouse)

                    # We will set the warehouse stock in saleor to match the stock in
                    # SAP. If there is more stock allocated (committed) in SAP than in
                    # Saleor, then we will reduce the total stock in saleor by the
                    # difference so that we don't oversell in Saleor. However, since we
                    # allow backordering in Saleor, overselling like this is likely
                    # inconsequential anyway.
                    variant_stock = Stock.objects.annotate_available_quantity().filter(
                        warehouse=warehouse,
                        product_variant_id=variant.id,
                    ).first()
                    if not variant_stock:
                        stock_reduction = 0
                    else:
                        allocated = variant_stock.quantity - \
                                    variant_stock.available_quantity

                        stock_reduction = max(
                            warehouse_data["Committed"] - allocated,
                            0
                        )

                    stock_data.append(
                        {
                            "warehouseId": warehouse_data["WarehouseCode"],
                            "quantity": warehouse_data["InStock"] - stock_reduction
                        }
                    )
        if warehouses:
            ProductVariantStocksUpdate.update_or_create_variant_stocks(
                variant, stock_data, warehouses
            )
        # Add size attribute, if we have it for this product
        if product_type.has_variants and product_type.variant_attributes:
            attributes_qs = product_type.variant_attributes
            # Saleor's specified types are flat-out wrong for this method, so...
            # noinspection PyTypeChecker
            attributes = AttributeAssignmentMixin.clean_input(
                [
                    {
                        "slug": "size",
                        "values": [sku.split("-")[-1]],
                    }
                ],
                attributes_qs,
                is_variant=True,
            )
            AttributeAssignmentMixin.save(variant, attributes)
        # Update the variant metadata
        variant_metadata = {
            "barCode": sap_product.get("BarCode", "") or ""
        }
        if variant_metadata:
            variant.store_value_in_metadata(items=variant_metadata)
            variant.save(update_fields=["metadata"])

        variant_private_metadata = {
            "onOrderWithVendor": sap_product.get("QuantityOrderedFromVendors", ""),
            "bestBuySku": sap_product.get("U_V33_BESTBUYSKU", "") or "",
        }
        if variant_private_metadata:
            variant.store_value_in_private_metadata(items=variant_private_metadata)
            variant.save(update_fields=["private_metadata"])

        # Look up all channels
        channel_slugs = set()
        for price_list in sap_product["ItemPrices"]:
            price_list["slug"] = slugify(price_list["PriceListName"])
            channel_slugs.add(price_list["slug"])
        channel_map = {
            x.slug: x
            for x in product_models.Channel.objects.filter(slug__in=channel_slugs).all()
        }
        # Make sure that our price lists are attached to the product
        update_channels = []
        for price_list in sap_product["ItemPrices"]:
            # We only support price lists that are already defined in Saleor, so check
            #  for a pre-existing channel
            channel = channel_map.get(price_list["slug"])
            if not channel:
                continue
            update_channels.append(
                {
                    "channel": channel,
                }
            )
        if update_channels:
            ProductChannelListingUpdate.update_channels(
                product, update_channels=update_channels
            )
        # And then adjust the prices for the variant in those channels
        price_updates = []
        for price_list in sap_product["ItemPrices"]:
            # Just like products, we only use pre-defined channels
            channel = channel_map.get(price_list["slug"])
            if not channel:
                continue
            price_updates.append(
                {
                    "channel": channel,
                    "price": round_money(price_list["Price"]),
                }
            )
        if price_updates:
            ProductVariantChannelListingUpdate.save(info, variant, price_updates)

        return cls(
            product_variant=ChannelContext(node=variant, channel_slug=None),
            errors=[],
        )
