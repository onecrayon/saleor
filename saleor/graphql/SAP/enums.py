import graphene

from firstech.permissions import get_customer_permissions_enum_list


class DistributionTypeEnum(graphene.Enum):
    STRIPE = "stripe"
    SAP = "SAP"


CustomerPermissionEnum = graphene.Enum(
    "CustomerPermissionEnum", get_customer_permissions_enum_list()
)
