from graphene import relay
from graphene_federation import key
from ..core.connection import CountableDjangoObjectType
from firstech.drone.models import DroneUserProfile as DroneUserProfileModel


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
        ]
