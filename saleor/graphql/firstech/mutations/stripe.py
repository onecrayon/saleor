import graphene
from django.core.exceptions import ValidationError

from firstech.permissions import SAPCustomerPermissions
from saleor.core.permissions import PaymentPermissions
from saleor.graphql.account.enums import CountryCodeEnum
from saleor.graphql.core.mutations import BaseMutation
from saleor.graphql.core.types.common import Error
from saleor.graphql.payment.enums import PaymentSourceType
from saleor.graphql.payment.types import (
    CreditCard,
    PaymentSource,
    PaymentSourceBillingInfo,
    BankAccount,
)
from saleor.payment import gateway
from saleor.payment.gateways.stripe_firstech.plugin import StripeGatewayPlugin
from saleor.payment.utils import fetch_customer_id


class PaymentSourceError(Error):
    code = graphene.String(description="The error code.", required=True)


class PaymentSourceCardInput(graphene.InputObjectType):
    number = graphene.String(required=False, description="Card number.")
    exp_month = graphene.Int(required=False, description="Card expiration month.")
    exp_year = graphene.Int(required=False, description="Card expiration year.")
    cvc = graphene.String(required=False, description="Card verification code.")


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

    credit_card_info = None
    if customer_source.credit_card_info:
        credit_card_info = CreditCard(
            brand=customer_source.credit_card_info.brand,
            first_digits=customer_source.credit_card_info.first_4,
            last_digits=customer_source.credit_card_info.last_4,
            exp_month=customer_source.credit_card_info.exp_month,
            exp_year=customer_source.credit_card_info.exp_year,
        )

    bank_account_info = None
    if customer_source.bank_account_info:
        bank_account_info = BankAccount(
            account_holder_name=customer_source.bank_account_info.account_holder_name,
            bank_name=customer_source.bank_account_info.bank_name,
            account_last_4=customer_source.bank_account_info.account_last_4,
            routing_number=customer_source.bank_account_info.routing_number,
            status=customer_source.bank_account_info.status,
        )

    if customer_source.billing_info:
        billing_info = PaymentSourceBillingInfo(
            name=customer_source.billing_info.first_name,
            street_address_1=customer_source.billing_info.street_address_1,
            street_address_2=customer_source.billing_info.street_address_2,
            city=customer_source.billing_info.city,
            state=customer_source.billing_info.country_area,
            postal_code=customer_source.billing_info.postal_code,
            country_code=customer_source.billing_info.country,
            phone=customer_source.billing_info.phone,
        )

    return cls(
        payment_source=PaymentSource(
            payment_method_id=customer_source.id,
            type=customer_source.type,
            is_default=customer_source.is_default,
            credit_card_info=credit_card_info,
            bank_account_info=bank_account_info,
            billing_info=billing_info,
        ),
        errors=[],
    )


class BaseStripeMutation(BaseMutation):
    class Meta:
        abstract = True

    @classmethod
    def validate_gateway(cls, gateway_id, manager):
        gateways_id = [gtw.id for gtw in manager.list_payment_gateways()]

        if gateway_id not in gateways_id:
            raise ValidationError("Method not available")


class CreateCustomerSession(BaseStripeMutation):
    ephemeralKey = graphene.String(description="Stripe EphemeralKey JSON")

    # Potentially this mutation will be removed if front-end developers confirm that
    # it is not useful

    class Meta:
        description = ("Create Stripe customer session to handle payment methods using "
                       "front-end Stripe SDK.")
        permissions = (SAPCustomerPermissions.PURCHASE_PRODUCTS_B2C,)
        error_type_class = Error
        error_type_field = "errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        gateway_id = StripeGatewayPlugin.PLUGIN_ID
        manager = info.context.plugins

        cls.validate_gateway(gateway_id, manager)

        user = info.context.user
        customer_id = fetch_customer_id(user=user, gateway=gateway_id)

        ephemeral_key = gateway.create_customer_session(
            gateway=gateway_id,
            manager=manager,
            customer={"id": customer_id, "email": user.email},
        )

        return cls(ephemeralKey=ephemeral_key, errors=[])


class CreateSetupIntent(BaseStripeMutation):
    client_secret = graphene.String(description="Client secret")

    class Meta:
        description = ("Create Stripe SetupIntent to handle payment method creation "
                       "using front-end Stripe SDK. This is the preferred way of "
                       "creating cards.")
        permissions = (SAPCustomerPermissions.PURCHASE_PRODUCTS_B2C,)
        error_type_class = Error
        error_type_field = "errors"

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        gateway_id = StripeGatewayPlugin.PLUGIN_ID
        manager = info.context.plugins

        cls.validate_gateway(gateway_id, manager)

        user = info.context.user
        customer_id = fetch_customer_id(user=user, gateway=gateway_id)

        client_secret = gateway.create_setup_intent(
            gateway=gateway_id,
            manager=manager,
            customer_info={"customer_id": customer_id, "customer_email": user.email},
        )

        return cls(client_secret=client_secret, errors=[])


class PaymentSourceCreate(BaseStripeMutation):
    payment_source = graphene.Field(
        PaymentSource, description="Created payment source."
    )

    class Meta:
        description = "Create payment source."
        permissions = (SAPCustomerPermissions.PURCHASE_PRODUCTS_B2C,)
        error_type_class = PaymentSourceError
        error_type_field = "payment_source_errors"

    class Arguments:
        type = PaymentSourceType(required=True, description="Payment source type.")
        is_default = graphene.Boolean(required=False)
        card = PaymentSourceCardInput(required=False, description="Card info.")
        billing_details = PaymentSourceBillingInfoInput(
            required=False, description="Payment method billing info."
        )
        token = graphene.String(required=False)

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
                    "state": billing_details_input.get("state"),
                    "country": billing_details_input.get("country_code"),
                    "line1": billing_details_input.get("street_address_1"),
                    "line2": billing_details_input.get("street_address_2"),
                    "postal_code": billing_details_input.get("postal_code"),
                },
                "email": billing_details_input.get("email"),
                "name": billing_details_input.get("name"),
                "phone": billing_details_input.get("phone"),
            }

        user = info.context.user
        customer_id = fetch_customer_id(user=user, gateway=gateway_id)

        payment_source_details = {
            "customer_id": customer_id,
            "is_default": data.get("is_default"),
            "type": data["type"],
            "card_info": data.get("card"),
            "billing_details": billing_details,
            "token": data.get("token"),
        }

        payment_source = gateway.create_payment_source(
            gateway=gateway_id,
            manager=manager,
            payment_source_details=payment_source_details,
        )

        return create_payment_source_response(cls, payment_source)


class PaymentSourceUpdate(BaseStripeMutation):
    payment_source = graphene.Field(
        PaymentSource, description="Updated payment source."
    )

    class Meta:
        description = "Update payment source."
        permissions = (SAPCustomerPermissions.PURCHASE_PRODUCTS_B2C,)
        error_type_class = PaymentSourceError
        error_type_field = "payment_source_errors"

    class Arguments:
        payment_source_id = graphene.String(
            description="Payment method identifier.", required=True
        )
        is_default = graphene.Boolean(required=False)
        card = PaymentSourceCardInput(description="Card info.", required=False)
        billing_details = PaymentSourceBillingInfoInput(
            description="Payment method billing info.", required=False
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
                    "state": billing_details_input.get("state"),
                    "country": billing_details_input.get("country_code"),
                    "line1": billing_details_input.get("street_address_1"),
                    "line2": billing_details_input.get("street_address_2"),
                    "postal_code": billing_details_input.get("postal_code"),
                },
                "email": billing_details_input.get("email"),
                "name": billing_details_input.get("name"),
                "phone": billing_details_input.get("phone"),
            }

        user = info.context.user
        customer_id = fetch_customer_id(user=user, gateway=gateway_id)

        payment_source_details = {
            "customer_id": customer_id,
            "is_default": data.get("is_default"),
            "payment_source_id": data["payment_source_id"],
            "billing_info": billing_details,
            "card_info": data.get("card"),
        }

        payment_source = gateway.update_payment_source(
            gateway=gateway_id,
            manager=manager,
            payment_source_details=payment_source_details,
        )

        return create_payment_source_response(cls, payment_source)

    @classmethod
    def validate_gateway(cls, gateway_id, manager):
        gateways_id = [gtw.id for gtw in manager.list_payment_gateways()]

        if gateway_id not in gateways_id:
            raise ValidationError("Method not available")


class PaymentSourceDelete(BaseStripeMutation):
    payment_source_id = graphene.String(description="Deleted payment source ID")

    class Meta:
        description = "Delete payment source."
        permissions = (SAPCustomerPermissions.PURCHASE_PRODUCTS_B2C,)
        error_type_class = PaymentSourceError
        error_type_field = "payment_source_errors"

    class Arguments:
        payment_source_type = PaymentSourceType(
            description="Payment method type.", required=True
        )
        payment_source_id = graphene.String(
            description="Payment method identifier.", required=True
        )

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        gateway_id = StripeGatewayPlugin.PLUGIN_ID
        manager = info.context.plugins

        cls.validate_gateway(gateway_id, manager)

        user = info.context.user
        customer_id = fetch_customer_id(user=user, gateway=gateway_id)

        payment_source_id = gateway.delete_payment_source(
            gateway=gateway_id,
            manager=manager,
            payment_source_info={
                "customer_id": customer_id,
                "payment_source_id": data["payment_source_id"],
                "payment_source_type": data["payment_source_type"],
            },
        )

        return cls(payment_source_id=payment_source_id, errors=[])


class PaymentSourceVerify(BaseStripeMutation):
    payment_source = graphene.Field(
        PaymentSource, description="Updated payment source."
    )

    class Meta:
        description = "Verify Stripe payment source"
        permissions = (SAPCustomerPermissions.PURCHASE_PRODUCTS_B2C,)
        error_type_class = PaymentSourceError
        error_type_field = "payment_source_errors"

    class Arguments:
        payment_source_id = graphene.String(required=True)
        bank_account_amounts = graphene.List(of_type=graphene.Int, required=True)

    @classmethod
    def perform_mutation(cls, _root, info, **data):
        gateway_id = StripeGatewayPlugin.PLUGIN_ID
        manager = info.context.plugins

        cls.validate_gateway(gateway_id, manager)

        user = info.context.user
        customer_id = fetch_customer_id(user=user, gateway=gateway_id)

        payment_source = gateway.verify_payment_source(
            gateway=gateway_id,
            manager=manager,
            verification_info={
                "customer_id": customer_id,
                "customer_email": user.email,
                "payment_source_id": data["payment_source_id"],
                "bank_account_amounts": data["bank_account_amounts"],
            },
        )

        return create_payment_source_response(cls, payment_source)
