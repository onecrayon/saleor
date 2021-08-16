from typing import Any

from django.db.models import Sum
from ..base_plugin import BasePlugin
from ...warehouse.models import Backorder
from saleor.product.models import ProductVariantChannelListing


class BackordersPlugin(BasePlugin):
    PLUGIN_ID = "firstech.backorders"
    PLUGIN_NAME = "Backorders"
    DEFAULT_ACTIVE = False
    CONFIGURATION_PER_CHANNEL = True

    def get_backorder_quantity_limit(self, variant_channel: ProductVariantChannelListing, previous_value) -> int:
        """Given a product variant channel listing, figure out how many units of that
        variant can be backordered at this time for the implied channel.

        If there are no limits defined for the product variant, then None will be
        returned.

        Backorder limits can be defined in 3 places:
        1. If the Backorder plugin is disabled for the channel then all products and
            variants will have a backorder limit 0.
        2. A global (across all channels) backorder threshold can be set at the product
            variant level.
        3. A threshold can be set at the variant/channel level.

        This threshold design imitates the limits for pre-orders to be introduced to
        Saleor 3.1.

        :param variant_channel: the ProductVariantCHannelListing object to determine
            backorder limits for
        :returns: The maximum remaining number of units that can be backordered for the
            given product and channel combination. Or None if no limit is defined.
        """
        if not self.active:
            return 0

        variant = variant_channel.variant
        # Get all the backorders for this variant grouped by channel and annotated by
        # quantity so that we can see how many units of this variant have been
        # backordered on each channel
        channel_backorders = (
            Backorder.objects.filter(
                product_variant_channel_listing__variant=variant
            )
            .order_by('product_variant_channel_listing__channel_id')
            .values("product_variant_channel_listing__channel_id")
            .annotate(channel_backordered=Sum("quantity"))
        )

        total_backordered = sum(
            [channel["channel_backordered"] for channel in channel_backorders]
        )

        limit = None
        if variant.backorder_quantity_global_threshold:
            limit = variant.backorder_quantity_global_threshold - total_backordered

        if variant_channel.backorder_quantity_threshold:
            channel_backordered = channel_backorders.filter(
                product_variant_channel_listing__channel_id=self.channel.id
            ).first()
            channel_limit = variant_channel.backorder_quantity_threshold \
                - channel_backordered["channel_backordered"]

            # Get the smallest non-null of the two limits
            limit = min(filter(None, [limit, channel_limit]))

        return limit

    def order_cancelled(self, order: "Order", previous_value: Any) -> Any:
        """Trigger when order is cancelled.
        """
        Backorder.objects.filter(
            order_line__order=order, quantity__gt=0
        ).delete()
