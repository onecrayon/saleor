from django.contrib.auth import models as auth_models
import graphene
from typing import Dict, Optional, List
from django.core.exceptions import ValidationError
from saleor.graphql.account.mutations.permission_group import (
    PermissionGroupCreate,
    PermissionGroupUpdate,
)
from saleor.graphql.SAP.enums import CustomerPermissionEnum
from ....core.permissions import AccountPermissions
from ...core.types.common import PermissionGroupError


class CustomerPermissionGroupInput(graphene.InputObjectType):
    add_permissions = graphene.List(
        graphene.NonNull(CustomerPermissionEnum),
        description="List of permission code names to assign to this group.",
        required=False,
    )
    add_users = graphene.List(
        graphene.NonNull(graphene.ID),
        description="List of users to assign to this group.",
        required=False,
    )


class CustomerPermissionGroupCreateInput(CustomerPermissionGroupInput):
    name = graphene.String(description="Group name.", required=True)


class CustomerPermissionGroupCreate(PermissionGroupCreate):
    class Arguments:
        input = CustomerPermissionGroupCreateInput(
            description="Input fields to create customer permission group.",
            required=True
        )

    class Meta:
        description = "Create new permission group for customers."
        model = auth_models.Group
        permissions = (AccountPermissions.MANAGE_STAFF,)
        error_type_class = PermissionGroupError
        error_type_field = "permission_group_errors"

    @classmethod
    def ensure_users_are_staff(
        cls,
        errors: Dict[Optional[str], List[ValidationError]],
        field: str,
        cleaned_input: dict,
    ):
        # The base class we are inheriting from uses this method to ensure only staff
        # users are assigned to a permission group, but we want to bypass that check.
        pass


class CustomerPermissionGroupUpdateInput(CustomerPermissionGroupInput):
    name = graphene.String(description="Group name.", required=False)
    remove_permissions = graphene.List(
        graphene.NonNull(CustomerPermissionEnum),
        description="List of customer permission code names "
                    "to unassign from this group.",
        required=False,
    )
    remove_users = graphene.List(
        graphene.NonNull(graphene.ID),
        description="List of users to unassign from this group.",
        required=False,
    )


class CustomerPermissionGroupUpdate(PermissionGroupUpdate):
    class Arguments:
        id = graphene.ID(description="ID of the group to update.", required=True)
        input = CustomerPermissionGroupUpdateInput(
            description="Input fields to create permission group.", required=True
        )

    class Meta:
        description = "Update customer permission group."
        model = auth_models.Group
        permissions = (AccountPermissions.MANAGE_STAFF,)
        error_type_class = PermissionGroupError
        error_type_field = "permission_group_errors"

    @classmethod
    def ensure_users_are_staff(
            cls,
            errors: Dict[Optional[str], List[ValidationError]],
            field: str,
            cleaned_input: dict,
    ):
        # The base class we are inheriting from uses this method to ensure only staff
        # users are assigned to a permission group, but we want to bypass that check.
        pass
