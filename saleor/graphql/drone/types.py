from graphene import relay
from graphene_federation import key

from firstech.drone.models import DroneUserProfile as DroneUserProfileModel

from ..core.connection import CountableDjangoObjectType


@key("id")
class DroneUserProfile(CountableDjangoObjectType):
    class Meta:
        description = "Drone Profile type description"
        model = DroneUserProfileModel
        interfaces = [relay.Node]
        only_fields = [
            "id",
            "drone_user_id",
            "cognito_sub",
            "is_company_owner",
        ]
