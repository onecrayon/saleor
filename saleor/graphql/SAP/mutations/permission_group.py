from collections import defaultdict
from typing import Dict, List, Optional

import graphene
from django.contrib.auth import models as auth_models
from django.core.exceptions import ValidationError

from firstech.permissions import SAPCustomerPermissions
from saleor.account.error_codes import PermissionGroupErrorCode
from saleor.account.models import User
from saleor.core.permissions import AccountPermissions
from saleor.graphql.account.mutations.permission_group import (
    PermissionGroupCreate,
    PermissionGroupUpdate,
)
from saleor.graphql.core.types.common import PermissionGroupError
from saleor.graphql.SAP.enums import CustomerPermissionEnum


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
            required=True,
        )

    class Meta:
        description = "Create new permission group for customers."
        model = auth_models.Group
        permissions = (AccountPermissions.MANAGE_USERS,)
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
        error_type_class = PermissionGroupError
        error_type_field = "permission_group_errors"

    @classmethod
    def clean_input(
        cls,
        info,
        instance,
        data,
    ):
        requester = info.context.user

        if requester.has_perm(AccountPermissions.MANAGE_USERS):
            # Staff with the manage users permission can perform any edits
            pass
        elif requester.has_perm(SAPCustomerPermissions.MANAGE_LINKED_INSTALLERS):
            # Dealers with the manage linked installers permission can add and remove
            # their installers from permission groups, but can't edit the name or
            # permissions of the group itself.
            errors = defaultdict(list)
            for field in ("add_permissions", "remove_permissions", "name"):
                if field in data:
                    errors[field].append(ValidationError("Cannot edit this field"))

            if errors:
                raise ValidationError(errors)
        else:
            raise PermissionError()

        cleaned_input = super().clean_input(info, instance, data)

        return cleaned_input

    @classmethod
    def clean_users(
        cls,
        requestor: "User",
        errors: dict,
        cleaned_input: dict,
        group: auth_models.Group,
    ):
        super().clean_users(requestor, errors, cleaned_input, group)
        if requestor.has_perm(AccountPermissions.MANAGE_USERS):
            return

        # Installers with the manage linked installer permission should only be able to
        # add or remove users that are in fact linked to them.
        users = set(
            cleaned_input.get("add_users", []) + cleaned_input.get("remove_users", [])
        )

        # Installers / Dealers should only have one business partner
        linked_installers = set(
            requestor.sapuserprofile.business_partners.get().company_contacts
        )

        if invalid_users := (users - linked_installers):
            invalid_user_ids = [
                graphene.Node.to_global_id("User", user.id) for user in invalid_users
            ]
            error_msg = "You can't manage these users."
            code = PermissionGroupErrorCode.OUT_OF_SCOPE_USER.value
            params = {"users": invalid_user_ids}
            cls.update_errors(errors, error_msg, None, code, params)

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
