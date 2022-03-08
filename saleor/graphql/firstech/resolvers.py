from itertools import chain

from saleor.core.tracing import traced_resolver
from saleor.graphql.payment.enums import PaymentSourceType
from saleor.payment import gateway
from saleor.payment.gateways.stripe_firstech.plugin import StripeGatewayPlugin
from saleor.payment.utils import fetch_customer_id


@traced_resolver
def resolve_payment_sources(info):
    manager = info.context.plugins
    user = info.context.user

    gateway_id = StripeGatewayPlugin.PLUGIN_ID
    customer_info = None
    if user.is_authenticated:
        customer_id = fetch_customer_id(user=user, gateway=gateway_id)
        customer_info = {"customer_id": customer_id, "customer_email": user.email}

    return list(
        prepare_graphql_payment_sources_type(
            gateway.list_payment_sources_stripe(gateway_id, customer_info, manager)
        )
    )


def prepare_graphql_payment_sources_type(payment_sources):
    sources = []
    for src in payment_sources:
        billing_info = None
        if src.billing_info:
            billing_info = {
                "name": src.billing_info.first_name,
                "street_address_1": src.billing_info.street_address_1,
                "street_address_2": src.billing_info.street_address_2,
                "city": src.billing_info.city,
                "state": src.billing_info.country_area,
                "postal_code": src.billing_info.postal_code,
                "country_code": src.billing_info.country,
                "phone": src.billing_info.phone,
            }
        credit_card_info = None
        if src.credit_card_info:
            credit_card_info = {
                "last_digits": src.credit_card_info.last_4,
                "exp_year": src.credit_card_info.exp_year,
                "exp_month": src.credit_card_info.exp_month,
                "brand": src.credit_card_info.brand,
                "first_digits": src.credit_card_info.first_4,
            }
        bank_account_info = None
        if src.bank_account_info:
            bank_account_info = {
                "account_holder_name": src.bank_account_info.account_holder_name,
                "bank_name": src.bank_account_info.bank_name,
                "account_last_4": src.bank_account_info.account_last_4,
                "routing_number": src.bank_account_info.routing_number,
                "status": src.bank_account_info.status,
            }
        sources.append(
            {
                "gateway": src.gateway,
                "payment_method_id": src.id,
                "type": src.type,
                "is_default": src.is_default,
                "credit_card_info": credit_card_info,
                "bank_account_info": bank_account_info,
                "billing_info": billing_info,
            }
        )
    return sources
