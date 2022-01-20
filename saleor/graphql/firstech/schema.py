import graphene

from .mutations.checkouts import B2BCheckoutCreate
from .mutations.orders import OrderLineCancel, OrderLineReduce
from saleor.graphql.firstech.mutations.payment_sources import (
    PaymentSourceCreate,
    PaymentSourceDelete,
    PaymentSourceUpdate
)


class FirstechOrderMutations(graphene.ObjectType):
    order_line_reduce = OrderLineReduce.Field()
    order_line_cancel = OrderLineCancel.Field()
    b2b_checkout_create = B2BCheckoutCreate.Field()


class StripePaymentSourcesMutations(graphene.ObjectType):
    payment_source_create = PaymentSourceCreate.Field()
    payment_source_delete = PaymentSourceDelete.Field()
    payment_source_update = PaymentSourceUpdate.Field()
