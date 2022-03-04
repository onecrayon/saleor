import pytest

from firstech.SAP.constants import CUSTOM_SAP_SHIPPING_TYPE_NAME
from saleor.account.models import Address
from saleor.graphql.SAP.mutations.orders import UpsertSAPOrder
from saleor.graphql.SAP.tests.fixtures import UPSERT_ORDER_MUTATION
from saleor.graphql.SAP.tests.utils import assert_address_match
from saleor.graphql.tests.utils import get_graphql_content
from saleor.order import OrderStatus
from saleor.order.models import Order
from saleor.shipping.models import ShippingMethod


@pytest.mark.vcr
def test_order_sync(
    staff_api_client,
    permission_manage_orders,
    sap_plugin,
    ecommerce_basic_setup,
    business_partner,
):
    """Test that a fresh order created in SAP and then synced to Saleor syncs correctly.
    Then tests that updating that order with some edits syncs correctly.
    """

    def assert_order_sync(order: Order, sap_order: dict):
        lines = order.lines.all()
        for i, line in enumerate(lines):
            assert line.product_sku == sap_order["DocumentLines"][i]["ItemCode"]
            assert line.quantity == sap_order["DocumentLines"][i]["Quantity"]

            # Unit price before discounts and before tax
            assert (
                line.undiscounted_unit_price_net_amount
                == sap_order["DocumentLines"][i]["UnitPrice"]
            )

            # Unit price after discount but before tax
            assert line.unit_price_net_amount == sap_order["DocumentLines"][i]["Price"]

            # Unit price after discount and tax
            assert (
                line.unit_price_gross_amount
                == sap_order["DocumentLines"][i]["PriceAfterVAT"]
            )

            # Total line item price (after discount and tax)
            assert (
                line.total_price_gross_amount
                == sap_order["DocumentLines"][i]["LineTotal"]
            )

        # total amount on order after discounts and taxes
        assert order.total_gross_amount == sap_order["DocTotal"]

        # The shipping method we would have if the price wasn't custom
        nominal_shipping_method = ShippingMethod.objects.filter(
            private_metadata__TrnspCode=str(sap_order["TransportationCode"])
        ).first()
        try:
            assert order.shipping_method.name == nominal_shipping_method.name
        except AssertionError:
            custom_shipping_method = ShippingMethod.objects.get(
                name=CUSTOM_SAP_SHIPPING_TYPE_NAME
            )
            assert order.shipping_method == custom_shipping_method
            assert order.shipping_method_name == \
                   nominal_shipping_method.name + " - CUSTOM"

        if sap_order["DocumentAdditionalExpenses"]:
            assert (
                order.shipping_price_net_amount
                == sap_order["DocumentAdditionalExpenses"][0]["LineTotal"]
            )

        assert order.status == OrderStatus.DRAFT

        assert order.user_email == "droneinator+mom@gmail.com"

        assert order.metadata["due_date"] == sap_order["DocDueDate"]
        assert order.metadata["po_number"] == sap_order["NumAtCard"]
        assert order.private_metadata["doc_entry"] == sap_order["DocEntry"]
        assert order.private_metadata["sap_bp_code"] == sap_order["CardCode"]

        billing_address = UpsertSAPOrder.parse_address_string(sap_order["Address"])
        billing_address = Address(
            company_name=sap_order["PayToCode"], **billing_address
        )
        assert_address_match(order.billing_address, billing_address)

        shipping_address = UpsertSAPOrder.parse_address_string(sap_order["Address2"])
        shipping_address = Address(
            company_name=sap_order["ShipToCode"], **shipping_address
        )
        assert_address_match(order.shipping_address, shipping_address)


    variables = {"doc_entry": 179667}
    response = staff_api_client.post_graphql(
        UPSERT_ORDER_MUTATION,
        variables=variables,
        permissions=[permission_manage_orders],
        check_no_permissions=False,
    )

    get_graphql_content(response)

    assert len(Order.objects.all()) == 1
    order = Order.objects.all().first()
    lines = order.lines.all()
    assert len(lines) == 1
    sap_sales_order_1 = sap_plugin.fetch_order(179667)
    assert_order_sync(order, sap_sales_order_1)

    # The order has been updated in SAP. The next time we make the get order request
    # with the SAP plugin we will receive the updated response from a different VCR
    # "cassette". These separate cassettes were created by running this test in the
    # debugger and making the updates to SAP while hanging at a breakpoint here.

    response = staff_api_client.post_graphql(
        UPSERT_ORDER_MUTATION,
        variables=variables,
        permissions=[permission_manage_orders],
        check_no_permissions=False,
    )

    content = get_graphql_content(response)

    # The existing order was patched, not a new one created
    assert len(Order.objects.all()) == 1
    order.refresh_from_db()
    lines = order.lines.all()
    assert len(lines) == 2
    sap_sales_order_2 = sap_plugin.fetch_order(179667)
    assert_order_sync(order, sap_sales_order_2)
