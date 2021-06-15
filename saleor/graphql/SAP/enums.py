import graphene


class DistributionTypeEnum(graphene.Enum):
    STRIPE = "stripe"
    SAP = "SAP"
