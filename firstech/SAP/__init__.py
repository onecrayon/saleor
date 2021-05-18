import logging

logger = logging.getLogger(__name__)


class DroneDistribution:
    STRIPE = "stripe"
    SAP = "SAP"

    CHOICES = [
        (STRIPE, "Stripe"),
        (SAP, "SAP")
    ]
