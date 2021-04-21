import logging

logger = logging.getLogger(__name__)


class PricingList:
    MSRP = "MSRP"
    DEALER = "dealer"
    PREFERRED = "preferred"

    PREFERRED_PLUS = "preferred_plus"
    ELITE = "elite"
    DISTRIBUTOR = "distributor"
    STRATEGIC_PARTNER = "strategic_partner"
    CAR_DEALER_DIRECT = "car_dealer_direct"
    MESA_GOLD = "mesa_gold"
    MESA_PLATINUM = "mesa_platinum"
    RPM_DEALER = "rpm_dealer"
    RPM_PROGRAM = "rpm_program"
    RPM_DISTRIBUTOR = "rpm_distributor"
    RPM_MESA_GOLD = "rpm_mesa_gold"
    RPM_MESA_PLATINUM = "rpm_mesa_platinum"
    RPM_STRATEGIC_PARTNER = "rpm_strategic_partner"
    SEGI_WARRANTY = "segi_warranty"
    SPECIAL_PRICING = "special_pricing"

    CHOICES = [
        (MSRP, "MSRP"),
        (DEALER, "Dealer"),
        (PREFERRED, "Preferred"),
        (PREFERRED_PLUS, "Preferred Plus"),
        (ELITE, "Elite"),
        (DISTRIBUTOR, "Distributor"),
        (STRATEGIC_PARTNER, "Strategic Partner"),
        (CAR_DEALER_DIRECT, "Car Dealer Direct"),
        (MESA_GOLD, "Mesa Gold"),
        (MESA_PLATINUM, "Mesa Platinum"),
        (RPM_DEALER, "RPM Dealer"),
        (RPM_PROGRAM, "RPM Program"),
        (RPM_DISTRIBUTOR, "RPM Distributor"),
        (RPM_MESA_GOLD, "RPM Mesa Gold"),
        (RPM_MESA_PLATINUM, "RPM Mesa Platinum"),
        (RPM_STRATEGIC_PARTNER, "RPM Strategic Partner"),
        (SEGI_WARRANTY, "Segi Warranty"),
        (SPECIAL_PRICING, "Special Pricing"),
    ]
