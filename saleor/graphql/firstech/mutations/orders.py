from django.core.exceptions import ValidationError

from ....core.permissions import OrderPermissions
from ....order import OrderLineData, OrderStatus, models
from ....order.actions import deallocate_stock
from ...core.types.common import OrderError
from ...order.mutations.orders import OrderLineDelete, OrderLineUpdate

ORDER_EDITABLE_STATUS = (OrderStatus.DRAFT, OrderStatus.UNCONFIRMED)


class OrderLineReduce(OrderLineUpdate):
    """Custom Firstech mutation for reducing line-item quantities after an order has
    been "confirmed". Mirumee's design assumes that orders are immutable once they have
    been finalized. We want to allow for line items to be reduced or cancelled, but not
    increased or added."""

    class Meta:
        description = "Reduces an order line of an order."
        model = models.OrderLine
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def validate_order(cls, order):
        pass

    @classmethod
    def clean_input(cls, info, instance, data):
        instance.old_quantity = instance.quantity
        cleaned_input = super().clean_input(info, instance, data)

        quantity = data["quantity"]
        if quantity > instance.old_quantity:
            raise ValidationError(
                {
                    "quantity": ValidationError(
                        "Cannot increase line item quantity. Items may only be removed "
                        "or cancelled entirely.",
                    )
                }
            )

        return cleaned_input

    @classmethod
    def save(cls, info, instance, cleaned_input):
        super().save(info, instance, cleaned_input)

        # TODO: Remove backordered stock first!!!

        deallocate_stock(
            [
                OrderLineData(
                    line=instance,
                    quantity=instance.old_quantity - instance.quantity,
                )
            ]
        )


class OrderLineCancel(OrderLineDelete):
    """Custom Firstech mutation for cancelling line-items after an order has
    been "confirmed". Mirumee's design assumes that orders are immutable once they have
    been finalized. We want to allow for line items to be reduced or cancelled, but not
    increased or added."""

    class Meta:
        description = "Deletes an order line from an order."
        permissions = (OrderPermissions.MANAGE_ORDERS,)
        error_type_class = OrderError
        error_type_field = "order_errors"

    @classmethod
    def validate_order(cls, order):
        pass
