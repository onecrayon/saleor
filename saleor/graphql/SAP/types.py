import graphene
from graphene import relay
from graphene_federation import key


from saleor.account.models import User as UserModel
from firstech.SAP import models
from ..core.connection import CountableDjangoObjectType


@key("id")
class BusinessPartner(CountableDjangoObjectType):
    company_contacts = graphene.List(
        "saleor.graphql.account.types.User",
        description="List of users at this business partner."
    )

    class Meta:
        description = "Business partner"
        model = models.BusinessPartner
        interfaces = [relay.Node]
        only_fields = [
            "addresses",
            "account_balance",
            "account_is_active",
            "account_purchasing_restricted",
            "company_contacts",
            "company_name",
            "company_url",
            "credit_limit",
            "customer_type",
            "debit_limit",
            # drone_rewards
            "inside_sales_rep",
            "internal_ft_notes",
            "outside_sales_rep",
            "outside_sales_rep_emails",
            "payment_terms",
            "pricing_list",
            "sales_manager",
            "sap_bp_code",
            "shipping_preference",
            "sync_partner",
            "warranty_preference",
        ]

    @staticmethod
    def resolve_company_contacts(root: models.BusinessPartner, _info, **kwargs):

        try:
            contact_ids = models.SAPUserProfile.objects.filter(
                business_partner=root
            ).values_list('user_id', flat=True)
            return UserModel.objects.filter(id__in=contact_ids).all()

        except models.SAPUserProfile.DoesNotExist:
            return None


@key("id")
class SAPUserProfile(CountableDjangoObjectType):
    class Meta:
        description = "SAP User Profile"
        model = models.SAPUserProfile
        interfaces = [relay.Node]
        only_fields = [
            "user",
            "date_of_birth",
            "is_company_owner",
            "business_partner",
        ]
