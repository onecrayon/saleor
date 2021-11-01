import graphene

from .mutations.checkouts import B2BCheckoutCreate
from .mutations.orders import OrderLineCancel, OrderLineReduce


class FirstechOrderMutations(graphene.ObjectType):
    order_line_reduce = OrderLineReduce.Field()
    order_line_cancel = OrderLineCancel.Field()
    b2b_checkout_create = B2BCheckoutCreate.Field()
