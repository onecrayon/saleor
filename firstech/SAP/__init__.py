import logging

from saleor.order import OrderStatus

logger = logging.getLogger(__name__)


CONFIRMED_ORDERS = (
    OrderStatus.UNFULFILLED,
    OrderStatus.PARTIALLY_FULFILLED,
    OrderStatus.FULFILLED,
    OrderStatus.PARTIALLY_RETURNED,
    OrderStatus.RETURNED,
    OrderStatus.CANCELED,
)


class DroneDistribution:
    STRIPE = "stripe"
    SAP = "SAP"

    CHOICES = [
        (STRIPE, "Stripe"),
        (SAP, "SAP")
    ]


class ReturnType:
    EXCHANGE = "exchange"
    CREDIT = "credit"
    ADVANCE = "advance"
    SPECIAL = "special"

    CHOICES = [
        (EXCHANGE, "Exchange"),
        (CREDIT, "Credit"),
        (ADVANCE, "Advance"),
        (SPECIAL, "Special"),
    ]


class ReturnStatus:
    PENDING = "pending"  # Return order has been requested by user
    APPROVED = "approved"  # Return order has been approved by staff
    CANCELED = "canceled"  # Return order has been denied by staff

    CHOICES = [
        (PENDING, "Pending"),
        (APPROVED, "Approved"),
        (CANCELED, "Canceled"),
    ]
