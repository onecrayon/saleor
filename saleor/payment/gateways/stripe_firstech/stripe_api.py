import logging
from contextlib import contextmanager
from decimal import Decimal
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import stripe
from django.contrib.sites.models import Site
from django.urls import reverse
from stripe.error import AuthenticationError, InvalidRequestError, StripeError
from stripe.stripe_object import StripeObject

from ....core.tracing import opentracing_trace
from ....core.utils import build_absolute_uri
from ...interface import PaymentMethodInfo
from ...utils import price_to_minor_unit
from .consts import (
    AUTOMATIC_CAPTURE_METHOD,
    MANUAL_CAPTURE_METHOD,
    METADATA_IDENTIFIER,
    PLUGIN_ID,
    STRIPE_API_VERSION,
    WEBHOOK_EVENTS,
    WEBHOOK_PATH,
    SOURCE_TYPE_BANK,
    SOURCE_TYPE_CARD,
)

logger = logging.getLogger(__name__)


@contextmanager
def stripe_opentracing_trace(span_name):
    with opentracing_trace(
        span_name=span_name, component_name="payment", service_name="stripe"
    ):
        yield


def is_secret_api_key_valid(api_key: str):
    """Call api to check if api_key is a correct key."""
    try:
        with stripe_opentracing_trace("stripe.WebhookEndpoint.list"):
            stripe.WebhookEndpoint.list(api_key, stripe_version=STRIPE_API_VERSION)
        return True
    except AuthenticationError:
        return False


def _extra_log_data(error: StripeError, payment_intent_id: Optional[str] = None):
    data = {
        "error_message": error.user_message,
        "http_status": error.http_status,
        "code": error.code,
    }
    if payment_intent_id is not None:
        data["payment_intent_id"] = payment_intent_id
    return data


def subscribe_webhook(api_key: str) -> Optional[StripeObject]:
    domain = Site.objects.get_current().domain
    api_path = reverse(
        "plugins-global",
        kwargs={"plugin_id": PLUGIN_ID},
    )

    base_url = build_absolute_uri(api_path)
    webhook_url = urljoin(base_url, WEBHOOK_PATH)  # type: ignore

    with stripe_opentracing_trace("stripe.WebhookEndpoint.create"):
        try:
            return stripe.WebhookEndpoint.create(
                api_key=api_key,
                url=webhook_url,
                enabled_events=WEBHOOK_EVENTS,
                metadata={METADATA_IDENTIFIER: domain},
                stripe_version=STRIPE_API_VERSION,
            )
        except StripeError as error:
            logger.warning(
                "Failed to create Stripe webhook",
                extra=_extra_log_data(error),
            )
            return None


def delete_webhook(api_key: str, webhook_id: str):
    try:
        with stripe_opentracing_trace("stripe.WebhookEndpoint.delete"):
            stripe.WebhookEndpoint.delete(
                webhook_id,
                api_key=api_key,
                stripe_version=STRIPE_API_VERSION,
            )
    except InvalidRequestError:
        # webhook doesn't exist
        pass


def get_or_create_customer(
    api_key: str,
    customer_id: Optional[str] = None,
    customer_email: Optional[str] = None,
) -> Optional[StripeObject]:
    try:
        if customer_id:
            with stripe_opentracing_trace("stripe.Customer.retrieve"):
                return stripe.Customer.retrieve(
                    customer_id,
                    api_key=api_key,
                    stripe_version=STRIPE_API_VERSION,
                )
        with stripe_opentracing_trace("stripe.Customer.create"):
            return stripe.Customer.create(
                api_key=api_key, email=customer_email, stripe_version=STRIPE_API_VERSION
            )
    except StripeError as error:
        logger.warning(
            "Failed to get/create Stripe customer",
            extra=_extra_log_data(error),
        )
        return None


def create_payment_intent(
    api_key: str,
    amount: Decimal,
    currency: str,
    auto_capture: bool = True,
    customer: Optional[StripeObject] = None,
    payment_method_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    setup_future_usage: Optional[str] = None,
    off_session: Optional[bool] = None,
    payment_method_types: Optional[List[str]] = None,
    customer_email: Optional[str] = None,
    line_items: Optional[List[dict]] = None,
) -> Tuple[Optional[StripeObject], Optional[StripeError]]:

    capture_method = AUTOMATIC_CAPTURE_METHOD if auto_capture else MANUAL_CAPTURE_METHOD
    additional_params = {}  # type: ignore

    if customer:
        additional_params["customer"] = customer

    if payment_method_id and customer:
        additional_params["payment_method"] = payment_method_id

        additional_params["off_session"] = off_session if off_session else False
        if off_session:
            additional_params["confirm"] = True

    if setup_future_usage in ["on_session", "off_session"] and not payment_method_id:
        additional_params["setup_future_usage"] = setup_future_usage

    if metadata:
        additional_params["metadata"] = metadata

    if payment_method_types and isinstance(payment_method_types, list):
        additional_params["payment_method_types"] = payment_method_types

    if customer_email:
        additional_params["receipt_email"] = customer_email

    if line_items:
        additional_params["line_items"] = line_items
    else:
        additional_params["amount"] = price_to_minor_unit(amount, currency)
        additional_params["currency"] = currency

    try:
        with stripe_opentracing_trace("stripe.PaymentIntent.create"):
            intent = stripe.PaymentIntent.create(
                api_key=api_key,
                capture_method=capture_method,
                stripe_version=STRIPE_API_VERSION,
                **additional_params,
            )
        return intent, None
    except StripeError as error:
        logger.warning(
            "Failed to create Stripe payment intent", extra=_extra_log_data(error)
        )
        return None, error


def create_payment_method(
    api_key: str,
    payment_method_type: str,
    card_info: Optional[dict] = None,
    billing_details: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> Tuple[Optional[StripeObject], Optional[StripeError]]:
    try:
        with stripe_opentracing_trace("stripe.PaymentMethod.create"):
            payment_method = stripe.PaymentMethod.create(
                api_key=api_key,
                type=payment_method_type,
                card=card_info,
                billing_details=billing_details,
                metadata=metadata,
            )
            return payment_method, None
    except StripeError as error:
        logger.warning(
            "Failed to create Stripe payment method", extra=_extra_log_data(error)
        )
        return None, error


def update_payment_method(api_key: str, payment_method_id: str):
    with stripe_opentracing_trace("stripe.PaymentMethod.modify"):
        try:
            stripe.PaymentMethod.modify(payment_method_id, api_key=api_key)
        except StripeError as error:
            logger.warning(
                "Failed to update payment method",
                extra=_extra_log_data(error),
            )


def update_payment_method_card(
    api_key: str,
    payment_method_id: str,
    card: dict,
    billing_details: dict,
    metadata: dict,
):
    with stripe_opentracing_trace("stripe.PaymentMethod.modify"):
        try:
            payment_method = stripe.PaymentMethod.modify(
                payment_method_id,
                api_key=api_key,
                card=card,
                billing_details=billing_details,
                metadata=metadata,
            )
            return payment_method, None
        except StripeError as error:
            logger.warning(
                "Failed to update payment method [card]",
                extra=_extra_log_data(error),
            )
            return None, error


def attach_payment_method(
    api_key: str, payment_method_id: str, customer_id: str
) -> Tuple[Optional[StripeObject], Optional[StripeError]]:
    try:
        with stripe_opentracing_trace("stripe.PaymentMethod.attach"):
            payment_method = stripe.PaymentMethod.attach(
                api_key=api_key, sid=payment_method_id, customer=customer_id
            )
        return payment_method, None
    except StripeError as error:
        return None, error


def detach_payment_method(
    api_key: str, payment_method_id: str
) -> Tuple[Optional[StripeObject], Optional[StripeError]]:
    try:
        with stripe_opentracing_trace("stripe.PaymentMethod.detach"):
            payment_method = stripe.PaymentMethod.detach(
                api_key=api_key, sid=payment_method_id
            )
        return payment_method, None
    except StripeError as error:
        return None, error


def delete_payment_source(
    api_key: str, customer_id: str, payment_source_id: str
) -> Tuple[Optional[StripeObject], Optional[StripeError]]:
    try:
        with stripe_opentracing_trace("stripe.Customer.delete_source"):
            response = stripe.Customer.delete_source(
                customer_id, payment_source_id, api_key=api_key
            )
        return response, None
    except StripeError as error:
        return None, error


def create_payment_source(api_key: str, token: str, customer_id: str):
    try:
        with stripe_opentracing_trace("stripe.Customer.create_source"):
            setup_intent = stripe.Customer.create_source(
                customer_id,
                source=token,
                api_key=api_key,
                stripe_version=STRIPE_API_VERSION,
            )
        return setup_intent, None
    except StripeError as error:
        logger.warning(
            "Unable to create Payment Source",
            extra=_extra_log_data(error),
        )

        return None, error


def verify_payment_source(
    api_key: str, customer_id: str, payment_source_id: str, amounts: list
) -> Tuple[Optional[StripeObject], Optional[StripeError]]:
    try:
        with stripe_opentracing_trace("stripe.Customer.retrieve_source"):
            payment_source = stripe.Customer.retrieve_source(
                customer_id, payment_source_id, api_key=api_key
            )
            payment_source = payment_source.verify(amounts=amounts)
        return payment_source, None
    except StripeError as error:
        logger.warning(
            "Unable to verify Source",
            extra=_extra_log_data(error),
        )

        return None, error


def create_ephemeral_key(api_key: str, customer_id: str):
    try:
        with stripe_opentracing_trace("stripe.EphemeralKey.create"):
            ephemeral_key = stripe.EphemeralKey.create(
                api_key=api_key,
                customer=customer_id,
                stripe_version=STRIPE_API_VERSION,
            )
        return ephemeral_key, None
    except StripeError as error:
        logger.warning(
            "Unable to create customer session",
            extra=_extra_log_data(error),
        )

        return None, error


def set_default_payment_source(
    api_key: str, customer_id: str, metadata: dict
) -> Tuple[Optional[StripeObject], Optional[StripeError]]:
    try:
        with stripe_opentracing_trace("stripe.Customer.modify"):
            customer = stripe.Customer.modify(
                customer_id,
                api_key=api_key,
                metadata=metadata,
                stripe_version=STRIPE_API_VERSION,
            )
        return customer, None
    except StripeError as error:
        return None, error


def list_customer_payment_methods(
    api_key: str, customer_id: str
) -> Tuple[Optional[StripeObject], Optional[StripeError]]:
    try:
        with stripe_opentracing_trace("stripe.PaymentMethod.list"):
            payment_methods = stripe.PaymentMethod.list(
                api_key=api_key,
                customer=customer_id,
                stripe_version=STRIPE_API_VERSION,
                type=SOURCE_TYPE_CARD,  # we support only cards for now
            )
        return payment_methods, None
    except StripeError as error:
        return None, error


def list_customer_sources(
    api_key: str, customer_id: str
) -> Tuple[Optional[StripeObject], Optional[StripeError]]:
    try:
        with stripe_opentracing_trace("stripe.Customer.list_sources"):
            payment_sources = stripe.Customer.list_sources(
                customer_id,
                api_key=api_key,
                object=SOURCE_TYPE_BANK,
                stripe_version=STRIPE_API_VERSION,
            )
        return payment_sources, None
    except StripeError as error:
        return None, error


def create_setup_intent(api_key: str, customer_id: str):
    try:
        with stripe_opentracing_trace("stripe.SetupIntent.create"):
            setup_intent = stripe.SetupIntent.create(
                api_key=api_key,
                customer=customer_id,
                stripe_version=STRIPE_API_VERSION,
            )
        return setup_intent, None
    except StripeError as error:
        logger.warning(
            "Unable to create SetupIntent",
            extra=_extra_log_data(error),
        )

        return None, error


def retrieve_payment_intent(
    api_key: str, payment_intent_id: str
) -> Tuple[Optional[StripeObject], Optional[StripeError]]:
    try:
        with stripe_opentracing_trace("stripe.PaymentIntent.retrieve"):
            payment_intent = stripe.PaymentIntent.retrieve(
                payment_intent_id,
                api_key=api_key,
                stripe_version=STRIPE_API_VERSION,
            )
        return payment_intent, None
    except StripeError as error:
        logger.warning(
            "Unable to retrieve a payment intent",
            extra=_extra_log_data(error),
        )
        return None, error


def capture_payment_intent(
    api_key: str, payment_intent_id: str, amount_to_capture: int
) -> Tuple[Optional[StripeObject], Optional[StripeError]]:
    try:
        with stripe_opentracing_trace("stripe.PaymentIntent.capture"):
            payment_intent = stripe.PaymentIntent.capture(
                payment_intent_id,
                amount_to_capture=amount_to_capture,
                api_key=api_key,
                stripe_version=STRIPE_API_VERSION,
            )
        return payment_intent, None
    except StripeError as error:
        logger.warning(
            "Unable to capture a payment intent",
            extra=_extra_log_data(error),
        )
        return None, error


def refund_payment_intent(
    api_key: str, payment_intent_id: str, amount_to_refund: int
) -> Tuple[Optional[StripeObject], Optional[StripeError]]:
    try:
        with stripe_opentracing_trace("stripe.Refund.create"):
            refund = stripe.Refund.create(
                payment_intent=payment_intent_id,
                amount=amount_to_refund,
                api_key=api_key,
                stripe_version=STRIPE_API_VERSION,
            )
        return refund, None
    except StripeError as error:
        logger.warning(
            "Unable to refund a payment intent",
            extra=_extra_log_data(error),
        )
        return None, error


def cancel_payment_intent(
    api_key: str, payment_intent_id: str
) -> Tuple[Optional[StripeObject], Optional[StripeError]]:
    try:
        with stripe_opentracing_trace("stripe.PaymentIntent.cancel"):
            payment_intent = stripe.PaymentIntent.cancel(
                payment_intent_id,
                api_key=api_key,
                stripe_version=STRIPE_API_VERSION,
            )
        return payment_intent, None
    except StripeError as error:
        logger.warning(
            "Unable to cancel a payment intent",
            extra=_extra_log_data(error),
        )

        return None, error


def construct_stripe_event(
    api_key: str, payload: bytes, sig_header: str, endpoint_secret: str
) -> StripeObject:
    with stripe_opentracing_trace("stripe.Webhook.construct_event"):
        return stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret, api_key=api_key
        )


def get_payment_method_details(
    payment_intent: StripeObject,
) -> Optional[PaymentMethodInfo]:
    charges = payment_intent.get("charges", None)
    payment_method_info = None
    if charges:
        charges_data = charges.get("data", [])
        if not charges_data:
            return None
        charge_data = charges_data[-1]
        payment_method_details = charge_data.get("payment_method_details", {})

        if payment_method_details.get("type") == SOURCE_TYPE_CARD:
            card_details = payment_method_details.get("card", {})
            exp_year = card_details.get("exp_year", "")
            exp_year = int(exp_year) if exp_year else None
            exp_month = card_details.get("exp_month", "")
            exp_month = int(exp_month) if exp_month else None
            payment_method_info = PaymentMethodInfo(
                last_4=card_details.get("last4", ""),
                exp_year=exp_year,
                exp_month=exp_month,
                brand=card_details.get("brand", ""),
                type=SOURCE_TYPE_CARD,
            )
    return payment_method_info
