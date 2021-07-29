import graphene

from .mutations.orders import OrderLineCancel, OrderLineReduce


class FirstechOrderMutations(graphene.ObjectType):
    order_line_reduce = OrderLineReduce.Field()
    order_line_cancel = OrderLineCancel.Field()
