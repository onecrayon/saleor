import graphene

from firstech.drone import models

from ...core.exceptions import PermissionDenied
from ...core.permissions import AccountPermissions
from ..decorators import permission_required
from ..utils import get_user_or_app_from_context
from .types import DroneUserProfile


class DroneQueries(graphene.ObjectType):
    drone_profile = graphene.Field(
        DroneUserProfile,
        id=graphene.Argument(
            graphene.ID,
            description="ID of the drone profile description in schema def"
        ),
    )

    @permission_required(AccountPermissions.MANAGE_USERS)
    def resolve_drone_profile(self, info, id=None, query=None, **kwargs):
        requester = get_user_or_app_from_context(info.context)
        if requester:
            filter_kwargs = {}
            _model, filter_kwargs["pk"] = graphene.Node.from_global_id(id)
            return models.DroneUserProfile.objects.filter(**filter_kwargs).first()

        return PermissionDenied()

