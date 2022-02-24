import graphene
from django.core.exceptions import ValidationError

from saleor.core.permissions import PaymentPermissions
from saleor.graphql.account.enums import CountryCodeEnum
from saleor.graphql.account.types import AddressInput
from saleor.graphql.core.mutations import BaseMutation
from saleor.graphql.core.types.common import Error
from saleor.graphql.payment.types import CreditCard, PaymentSource, \
    PaymentSourceBillingInfo
from saleor.payment import gateway
from saleor.payment.gateways.stripe_firstech.plugin import StripeGatewayPlugin
from saleor.payment.utils import fetch_customer_id


class PaymentSourceError(Error):
    code = graphene.String(description="The error code.", required=True)


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


class PaymentSourceBillingInfoInput(graphene.InputObjectType):
    name = graphene.String()
    street_address_1 = graphene.String()
    street_address_2 = graphene.String()
    city = graphene.String()
    state = graphene.String()
    postal_code = graphene.String()
    country_code = graphene.InputField(CountryCodeEnum)
    email = graphene.String()
    phone = graphene.String()


def create_payment_source_response(cls, customer_source):
    billing_info = None
    if customer_source.billing_info:
        billing_info = PaymentSourceBillingInfo(
            name=customer_source.billing_info.first_name,
            street_address_1=customer_source.billing_info.street_address_1,
            street_address_2=customer_source.billing_info.street_address_2,
            city=customer_source.billing_info.city,
            state=customer_source.billing_info.city_area,
            postal_code=customer_source.billing_info.postal_code,
            country_code=customer_source.billing_info.country,
            phone=customer_source.billing_info.phone
        )

    return cls(**{
        "payment_source": PaymentSource(
            payment_method_id=customer_source.id,
            credit_card_info=CreditCard(
                brand=customer_source.credit_card_info.brand,
                first_digits=customer_source.credit_card_info.first_4,
                last_digits=customer_source.credit_card_info.last_4,
                exp_month=customer_source.credit_card_info.exp_month,
                exp_year=customer_source.credit_card_info.exp_year
            ),
            billing_info=billing_info
        ),
        "errors": []
    })


class CreateCustomerSession(BaseMutation):
    ephemeralKey = graphene.String(description="EphemeralKey JSON")

    class Meta:
        description = "Create Stripe customer session"
        permissions = ()
        error_type_class = Error
        error_type_field = "errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        gateway_id = StripeGatewayPlugin.PLUGIN_ID
        manager = info.context.plugins

        cls.validate_gateway(gateway_id, manager)

        user = info.context.user
        customer_id = None
        if user.is_authenticated:
            customer_id = fetch_customer_id(user=user, gateway=gateway_id)

        ephemeral_key = gateway.create_customer_session(
            gateway=gateway_id,
            manager=manager,
            customer={
                "id": customer_id,
                "email": user.email
            },
            channel_slug=""
        )

        return cls(**{
            "ephemeralKey": ephemeral_key,
            "errors": []
        })

    @classmethod
    def validate_gateway(cls, gateway_id, manager):
        gateways_id = [gtw.id for gtw in manager.list_payment_gateways()]

        if gateway_id not in gateways_id:
            raise ValidationError("Method not available")


class CreateSetupIntent(BaseMutation):
    client_secret = graphene.String(description="Client secret")

    class Meta:
        description = "Create Stripe SetupIntent"
        permissions = ()
        error_type_class = Error
        error_type_field = "errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        gateway_id = StripeGatewayPlugin.PLUGIN_ID
        manager = info.context.plugins

        cls.validate_gateway(gateway_id, manager)

        user = info.context.user
        customer_id = None
        if user.is_authenticated:
            customer_id = fetch_customer_id(user=user, gateway=gateway_id)

        client_secret = gateway.create_setup_intent(
            gateway=gateway_id,
            manager=manager,
            customer={
                "customer_id": customer_id,
                "customer_email": user.email
            },
            channel_slug=""
        )

        return cls(**{
            "client_secret": client_secret,
            "errors": []
        })

    @classmethod
    def validate_gateway(cls, gateway_id, manager):
        gateways_id = [gtw.id for gtw in manager.list_payment_gateways()]

        if gateway_id not in gateways_id:
            raise ValidationError("Method not available")


class PaymentSourceCreate(BaseMutation):
    payment_source = graphene.Field(PaymentSource,
                                    description="Created payment source.")

    class Meta:
        description = "Create payment source."
        permissions = (PaymentPermissions.HANDLE_PAYMENTS,)
        error_type_class = PaymentSourceError
        error_type_field = "payment_source_errors"

    class Arguments:
        type = graphene.String(
            required=True, description="Payment source type."
        )
        card = PaymentSourceCardInput(
            required=False, description="Card info."
        )
        billing_details = PaymentSourceBillingInfoInput(
            required=False, description="Payment method billing info."
        )

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        gateway_id = StripeGatewayPlugin.PLUGIN_ID
        manager = info.context.plugins

        cls.validate_gateway(gateway_id, manager)

        billing_details_input = data.get("billing_details")
        billing_details = None
        if billing_details_input:
            billing_details = {
                "address": {
                    "city": billing_details_input.get("city"),
                    "state": billing_details_input.get("country_area"),
                    "country": billing_details_input.get("country"),
                    "line1": billing_details_input.get("street_address_1"),
                    "line2": billing_details_input.get("street_address_2"),
                    "postal_code": billing_details_input.get("postal_code"),
                },
                "email": billing_details_input.get("email"),
                "name": billing_details_input.get("name"),
                "phone": billing_details_input.get("phone")
            }

        channel_slug = data.get("channel")

        user = info.context.user
        customer_id = None
        if user.is_authenticated:
            customer_id = fetch_customer_id(user=user, gateway=gateway_id)

        payment_source_details = {
            "customer_id": customer_id,
            "type": data.get("type"),
            "card_info": data.get("card"),
            "billing_details": billing_details
        }

        payment_source = gateway.create_payment_source(
            gateway=gateway_id,
            manager=manager,
            payment_source_details=payment_source_details,
            channel_slug=channel_slug
        )

        return create_payment_source_response(cls, payment_source)

    @classmethod
    def validate_gateway(cls, gateway_id, manager):
        gateways_id = [gtw.id for gtw in manager.list_payment_gateways()]

        if gateway_id not in gateways_id:
            raise ValidationError("Method not available")


class PaymentSourceUpdate(BaseMutation):
    payment_source = graphene.Field(PaymentSource,
                                    description="Updated payment source.")

    class Meta:
        description = "Update payment source."
        permissions = (PaymentPermissions.HANDLE_PAYMENTS,)
        error_type_class = PaymentSourceError
        error_type_field = "payment_source_errors"

    class Arguments:
        payment_method_id = graphene.String(
            description="Payment method identifier.",
            required=True
        )
        card = PaymentSourceCardInput(
            description="Card info.",
            required=False
        )
        billing_details = PaymentSourceBillingInfoInput(
            description="Payment method billing info.",
            required=False
        )

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        gateway_id = StripeGatewayPlugin.PLUGIN_ID
        manager = info.context.plugins

        cls.validate_gateway(gateway_id, manager)

        billing_details_input = data.get("billing_details")
        billing_details = None
        if billing_details_input:
            billing_details = {
                "address": {
                    "city": billing_details_input.get("city"),
                    "state": billing_details_input.get("country_area"),
                    "country": billing_details_input.get("country"),
                    "line1": billing_details_input.get("street_address_1"),
                    "line2": billing_details_input.get("street_address_2"),
                    "postal_code": billing_details_input.get("postal_code"),
                },
                "email": billing_details_input.get("email"),
                "name": billing_details_input.get("name"),
                "phone": billing_details_input.get("phone")
            }

        payment_source_details = {
            "payment_method_id": data.get("payment_method_id"),
            "billing_info": billing_details,
            "card_info": data.get("card")
        }

        channel_slug = data.get("channel")

        payment_source = gateway.update_payment_source(
            gateway=gateway_id,
            manager=manager,
            payment_source_details=payment_source_details,
            channel_slug=channel_slug
        )

        return create_payment_source_response(cls, payment_source)

    @classmethod
    def validate_gateway(cls, gateway_id, manager):
        gateways_id = [gtw.id for gtw in manager.list_payment_gateways()]

        if gateway_id not in gateways_id:
            raise ValidationError("Method not available")


class PaymentSourceDelete(BaseMutation):
    payment_source = graphene.Field(PaymentSource,
                                    description="Deleted payment source.")

    class Meta:
        description = "Delete payment source."
        permissions = (PaymentPermissions.HANDLE_PAYMENTS,)
        error_type_class = PaymentSourceError
        error_type_field = "payment_source_errors"

    class Arguments:
        payment_method_id = graphene.String(
            description="Payment method identifier.",
            required=True
        )

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        gateway_id = StripeGatewayPlugin.PLUGIN_ID
        manager = info.context.plugins

        cls.validate_gateway(gateway_id, manager)

        channel_slug = data.get("channel")

        payment_source = gateway.delete_payment_source(
            gateway=gateway_id,
            manager=manager,
            payment_source_id=data.get("payment_method_id"),
            channel_slug=channel_slug
        )

        return create_payment_source_response(cls, payment_source)

    @classmethod
    def validate_gateway(cls, gateway_id, manager):
        gateways_id = [gtw.id for gtw in manager.list_payment_gateways()]

        if gateway_id not in gateways_id:
            raise ValidationError("Method not available")
