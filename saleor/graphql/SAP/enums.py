import graphene

from firstech.permissions import get_customer_permissions_enum_list


class DistributionTypeEnum(graphene.Enum):
    STRIPE = "stripe"
    SAP = "SAP"


class ReturnTypeEnum(graphene.Enum):
    EXCHANGE = "exchange"
    CREDIT = "credit"
    ADVANCE = "advance"
    SPECIAL = "special"


CustomerPermissionEnum = graphene.Enum(
    "CustomerPermissionEnum", get_customer_permissions_enum_list()
)
