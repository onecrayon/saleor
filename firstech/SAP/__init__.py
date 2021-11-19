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
