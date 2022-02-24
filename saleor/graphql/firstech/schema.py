import graphene

from .mutations.checkouts import B2BCheckoutCreate
from .mutations.orders import OrderLineCancel, OrderLineReduce
from saleor.graphql.firstech.mutations.stripe import (
    CreateCustomerSession,
    CreateSetupIntent,
    PaymentSourceCreate,
    PaymentSourceDelete,
    PaymentSourceUpdate,
)


class FirstechOrderMutations(graphene.ObjectType):
    order_line_reduce = OrderLineReduce.Field()
    order_line_cancel = OrderLineCancel.Field()
    b2b_checkout_create = B2BCheckoutCreate.Field()


class FirstechStripeMutations(graphene.ObjectType):
    create_customer_session = CreateCustomerSession.Field()
    create_setup_intent = CreateSetupIntent.Field()
    payment_source_create = PaymentSourceCreate.Field()
    payment_source_delete = PaymentSourceDelete.Field()
    payment_source_update = PaymentSourceUpdate.Field()
