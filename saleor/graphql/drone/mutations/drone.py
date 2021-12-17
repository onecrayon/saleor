import graphene

from firstech.drone.models import get_or_create_user_with_drone_profile, \
    DroneUserProfile
from saleor.core.permissions import AccountPermissions
from saleor.graphql.core.mutations import BaseMutation
from saleor.graphql.core.types.common import AccountError
from saleor.graphql.drone.types import DroneUserProfile as DroneUserProfileType


class RefreshDroneProfile(BaseMutation):
    drone_profile = graphene.Field(DroneUserProfileType)

    class Arguments:
        email = graphene.String(required=True, description="Email address of the user.")

    class Meta:
        description = "Forces a refresh of the drone user profile attached to the email"
        permissions = (AccountPermissions.MANAGE_USERS, AccountPermissions.MANAGE_STAFF)
        error_type_class = AccountError
        error_type_field = "account_errors"

    @classmethod
    def perform_mutation(cls, root, info, **data):
        user = get_or_create_user_with_drone_profile(token_email=data["email"])
        if user:
            try:
                return RefreshDroneProfile(drone_profile=user.droneuserprofile)
            except DroneUserProfile.DoesNotExist:
                pass

        return RefreshDroneProfile(drone_profile=None)
