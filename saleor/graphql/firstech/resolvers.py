from saleor.core.tracing import traced_resolver
from saleor.payment import gateway
from saleor.payment.gateways.stripe_firstech.plugin import StripeGatewayPlugin
from saleor.payment.utils import fetch_customer_id


@traced_resolver
def resolve_default_payment_method(info):
    manager = info.context.plugins
    user = info.context.user

    gateway_id = StripeGatewayPlugin.PLUGIN_ID
    channel_slug = ""
    customer_id = None
    if user.is_authenticated:
        customer_id = fetch_customer_id(user=user, gateway=gateway_id)

    return gateway.default_payment_method(
        gateway_id,
        customer={
            "customer_id": customer_id,
            "customer_email": user.email,
        },
        manager=manager,
        channel_slug=channel_slug
    )
