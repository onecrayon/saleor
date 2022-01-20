import graphene
from stripe.error import StripeError

from saleor.graphql.account.i18n import I18nMixin

from saleor.core.permissions import PaymentPermissions
from saleor.payment import gateway
from saleor.graphql.account.types import AddressInput
from saleor.graphql.core.mutations import BaseMutation, ModelMutation
from saleor.graphql.core.types.common import AccountError
from saleor.core.tracing import traced_atomic_transaction
from saleor.payment.gateways.stripe.plugin import StripeGatewayPlugin
from saleor.graphql.payment.types import CreditCard, PaymentSource


class PaymentSourceCardInput(graphene.InputObjectType):
    number = graphene.String(
        required=False, description="Card number."
    )
    exp_month = graphene.Int(
        required=False, description="Card expiration month."
    )
    exp_year = graphene.Int(
        required=False, description="Card expiration year."
    )
    cvc = graphene.String(
        required=False, description="Card verification code."
    )


def resolve_payment_source(customer_source):
    return PaymentSource(
        payment_method_id=customer_source.id,
        credit_card_info=CreditCard(
            brand=customer_source.credit_card_info.brand,
            first_digits=customer_source.credit_card_info.first_4,
            last_digits=customer_source.credit_card_info.last_4,
            exp_month=customer_source.credit_card_info.exp_month,
            exp_year=customer_source.credit_card_info.exp_year
        )
    )


class PaymentSourceCreate(BaseMutation):
    payment_source = graphene.Field(PaymentSource, description="")

    class Meta:
        description = "Create payment source."
        permissions = (PaymentPermissions.HANDLE_PAYMENTS,)
        error_type_class = AccountError
        error_type_field = "account_errors"

    class Arguments:
        type = graphene.String(
            required=True, description="Payment source type."
        )
        card = PaymentSourceCardInput(
            required=False, description="Card info."
        )

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        payment_source_details = {
            "type": data.get("type"),
            "card_info": data.get("card")
        }

        channel_slug = ""

        manager = info.context.plugins

        payment_source = gateway.create_payment_source(
            gateway=StripeGatewayPlugin.PLUGIN_ID,
            manager=manager,
            payment_source_details=payment_source_details,
            channel_slug=channel_slug
        )

        return cls(**{"payment_source": resolve_payment_source(payment_source), "errors": []})


class PaymentSourceUpdate(BaseMutation, I18nMixin):
    payment_source = graphene.Field(PaymentSource, description="")

    class Meta:
        description = "Update payment source."
        permissions = (PaymentPermissions.HANDLE_PAYMENTS,)
        error_type_class = AccountError
        error_type_field = "account_errors"

    class Arguments:
        payment_method_id = graphene.String(
            description="Payment method identifier.",
            required=True
        )
        billing_details = AddressInput(
            description="Payment method billing info.",
            required=False
        )
        card = PaymentSourceCardInput(
            required=False, description="Card info."
        )

    @classmethod
    @traced_atomic_transaction()
    def perform_mutation(cls, _root, info, **data):
        payment_source_details = {
            "payment_method_id": data.get("payment_method_id"),
            "billing_info": data.get("billing_details"),
            "card_info": data.get("card")
        }

        channel_slug = ""

        manager = info.context.plugins

        payment_source = gateway.update_payment_source(
            gateway=StripeGatewayPlugin.PLUGIN_ID,
            manager=manager,
            payment_source_details=payment_source_details,
            channel_slug=channel_slug
        )

        return cls(**{
            "payment_source": resolve_payment_source(payment_source),
            "errors": []
        })


class PaymentSourceDelete(BaseMutation):
    payment_source = graphene.Field(PaymentSource, description="")

    class Meta:
        description = "Delete payment source."
        permissions = (PaymentPermissions.HANDLE_PAYMENTS,)
        error_type_class = AccountError
        error_type_field = "account_errors"

    class Arguments:
        payment_method_id = graphene.String(
            description="Payment method identifier.",
            required=True
        )

    @classmethod
    @traced_atomic_transaction()
    def perform_mutation(cls, _root, info, **data):
        manager = info.context.plugins

        channel_slug = ""

        try:
            payment_source = gateway.delete_payment_source(
                gateway=StripeGatewayPlugin.PLUGIN_ID,
                manager=manager,
                payment_source_id=data.get("payment_method_id"),
                channel_slug=channel_slug
            )
        except StripeError as error:
            return cls(**{
                "errors": []
            })
        else:
            return cls(**{
                "payment_source": resolve_payment_source(payment_source),
                "errors": ["error_message"]
            })
