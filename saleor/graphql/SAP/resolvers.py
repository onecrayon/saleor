import graphene

from firstech.SAP import models
from firstech.permissions import SAPCustomerPermissions
from saleor.core.exceptions import PermissionDenied
from saleor.core.permissions import AccountPermissions
from saleor.graphql.core.validators import validate_one_of_args_is_in_query
from saleor.graphql.utils import get_user_or_app_from_context


def filter_business_partner_by_permissions(business_partner_qs, requester):
    """Given a queryset of BusinessPartner, and a requesting user, filter and return
    the queryset to only contain business partners that the user has permission to view
    """
    if requester.has_perm(AccountPermissions.MANAGE_USERS):
        return business_partner_qs
    elif requester.has_perm(SAPCustomerPermissions.VIEW_PROFILE):
        # Non-staff can only see business partners they are attached to
        users_bps = requester.sapuserprofile.business_partners.values_list(
            "id", flat=True
        )
        return business_partner_qs.filter(id__in=users_bps)
    else:
        return business_partner_qs.none()


def resolve_business_partner(_root, info, id=None, sapBpCode=None, **kwargs):
    """Resolves a business partner by id or card code"""
    validate_one_of_args_is_in_query("id", id, "sapBpCode", sapBpCode)
    requester = get_user_or_app_from_context(info.context)
    if requester:
        filter_kwargs = {}
        if id:
            _model, filter_kwargs["pk"] = graphene.Node.from_global_id(id)
        elif sapBpCode:
            filter_kwargs["sap_bp_code"] = sapBpCode

        queryset = models.BusinessPartner.objects.filter(**filter_kwargs)

        return filter_business_partner_by_permissions(queryset, requester).first()

    return PermissionDenied()
