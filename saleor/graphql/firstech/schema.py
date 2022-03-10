import graphene

from .mutations.checkouts import B2BCheckoutCreate
from .mutations.orders import OrderLineCancel, OrderLineReduce
from saleor.graphql.firstech.mutations.stripe import (
    CreateCustomerSession,
    CreateSetupIntent,
    PaymentSourceCreate,
    PaymentSourceDelete,
    PaymentSourceUpdate,
    PaymentSourceVerify,
)
from .resolvers import resolve_payment_sources
from ...core.exceptions import PermissionDenied


class FirstechOrderMutations(graphene.ObjectType):
    order_line_reduce = OrderLineReduce.Field()
    order_line_cancel = OrderLineCancel.Field()
    b2b_checkout_create = B2BCheckoutCreate.Field()


class FirstechStripeMutations(graphene.ObjectType):
    create_setup_intent = CreateSetupIntent.Field()
    payment_source_create = PaymentSourceCreate.Field()
    payment_source_delete = PaymentSourceDelete.Field()
    payment_source_update = PaymentSourceUpdate.Field()
    payment_source_verify = PaymentSourceVerify.Field()
    create_customer_session = CreateCustomerSession.Field()


class FirstechStripeQueries(graphene.ObjectType):
    stored_payment_sources = graphene.List(
        "saleor.graphql.payment.types.PaymentSource",
        description="List of stored payment sources.",
        channel=graphene.String(
            description="Slug of a channel for which the data should be returned."
        ),
    )

    @staticmethod
    def resolve_stored_payment_sources(self, info):
        return resolve_payment_sources(info)
