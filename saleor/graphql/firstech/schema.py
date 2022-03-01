import graphene

from .mutations.checkouts import B2BCheckoutCreate
from .mutations.orders import OrderLineCancel, OrderLineReduce
from saleor.graphql.firstech.mutations.stripe import (
    CreateCustomerSession,
    CreateSetupIntent,
    PaymentMethodCreate,
    PaymentMethodDelete,
    PaymentMethodUpdate,
    PaymentSourceCreate,
    PaymentSourceVerify, SaveDefaultPaymentMethod,
)
from .resolvers import resolve_default_payment_method


class FirstechOrderMutations(graphene.ObjectType):
    order_line_reduce = OrderLineReduce.Field()
    order_line_cancel = OrderLineCancel.Field()
    b2b_checkout_create = B2BCheckoutCreate.Field()


class FirstechStripeMutations(graphene.ObjectType):
    create_customer_session = CreateCustomerSession.Field()
    create_setup_intent = CreateSetupIntent.Field()
    payment_method_create = PaymentMethodCreate.Field()
    payment_method_delete = PaymentMethodDelete.Field()
    payment_method_update = PaymentMethodUpdate.Field()
    payment_source_create = PaymentSourceCreate.Field()
    payment_source_verify = PaymentSourceVerify.Field()
    save_default_payment_method = SaveDefaultPaymentMethod.Field()


class FirstechStripeQueries(graphene.ObjectType):
    default_payment_method = graphene.String()

    def resolve_default_payment_method(self, info):
        return resolve_default_payment_method(info)
