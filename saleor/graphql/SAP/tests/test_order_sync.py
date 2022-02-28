from unittest.mock import patch

from firstech.SAP.constants import CUSTOM_SAP_SHIPPING_TYPE_NAME
from saleor.account.models import Address
from saleor.graphql.SAP.tests.utils import assert_address_match
from saleor.graphql.tests.utils import get_graphql_content
from saleor.order import OrderStatus
from saleor.order.models import Order
from saleor.plugins.sap_orders.plugin import SAPPlugin
from saleor.shipping.models import ShippingMethod

UPSERT_ORDER_MUTATION = """
    mutation upsertOrder($doc_entry: Int!){
        upsertSapOrder(docEntry: $doc_entry){
            errors{
                field
                message
            }
        }
    }
"""


@patch.object(SAPPlugin, "fetch_sales_person")
@patch.object(SAPPlugin, "fetch_payment_terms")
@patch.object(SAPPlugin, "fetch_shipping_type")
@patch.object(SAPPlugin, "fetch_business_partner")
@patch.object(SAPPlugin, "fetch_order")
def test_order_sync(
    fetch_order_mock,
    fetch_business_partner_mock,
    fetch_shipping_type_mock,
    fetch_payment_terms_mock,
    fetch_sales_person_mock,
    staff_api_client,
    permission_manage_orders,
    sap_plugin,
    sap_sales_order,
    updated_sap_sales_order,
    sap_shipping_types,
    sap_business_partner,
    ecommerce_basic_setup,
    payment_terms,
    sales_person,
):
    """Test that a fresh order created in SAP and then synced to Saleor syncs correctly.
    Then tests that updating that order with some edits syncs correctly.
    """

    def fetch_shipping_type(code: int):
        for shipping_type in sap_shipping_types:
            if shipping_type["Code"] == code:
                return shipping_type

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
        # The actual shipping method that is applied becuase we have a custom price
        shipping_method = ShippingMethod.objects.get(name=CUSTOM_SAP_SHIPPING_TYPE_NAME)

        assert order.shipping_method == shipping_method
        assert order.shipping_method_name == nominal_shipping_method.name + " - CUSTOM"

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

        assert_address_match(
            order.shipping_address,
            Address(
                company_name=sap_order["ShipToCode"],
                street_address_1="123 5th ave",
                street_address_2="",
                city="NEW YORK CITY",
                country_area="NY",
                country="USA",
                postal_code="10006",
            ),
        )

        assert_address_match(
            order.billing_address,
            Address(
                company_name=sap_order["PayToCode"],
                street_address_1="123 4th ave",
                street_address_2="",
                city="NEW YORK CITY",
                country_area="NY",
                country="USA",
                postal_code="10006",
            ),
        )

    fetch_order_mock.return_value = sap_sales_order
    fetch_business_partner_mock.return_value = sap_business_partner
    fetch_shipping_type_mock.side_effect = fetch_shipping_type
    fetch_payment_terms_mock.return_value = payment_terms
    fetch_sales_person_mock.return_value = sales_person

    variables = {"doc_entry": 179667}
    response = staff_api_client.post_graphql(
        UPSERT_ORDER_MUTATION,
        variables=variables,
        permissions=[permission_manage_orders],
        check_no_permissions=False,
    )

    content = get_graphql_content(response)

    assert len(Order.objects.all()) == 1
    order = Order.objects.all().first()
    lines = order.lines.all()
    assert len(lines) == 1
    assert_order_sync(order, sap_sales_order)

    ## Update the order in SAP
    fetch_order_mock.return_value = updated_sap_sales_order

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
    assert_order_sync(order, updated_sap_sales_order)
