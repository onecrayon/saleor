from datetime import timedelta

import pytest
from django.utils import timezone

from firstech.SAP.models import SAPSalesManager
from saleor.account.models import Address, User
from saleor.channel.models import Channel
from saleor.plugins.manager import get_plugins_manager
from saleor.plugins.models import PluginConfiguration
from saleor.plugins.sap_orders.plugin import SAPPlugin
from saleor.product.models import (
    Product,
    ProductChannelListing,
    ProductType,
    ProductVariant,
    ProductVariantChannelListing,
)
from saleor.shipping.models import (
    ShippingMethod,
    ShippingMethodChannelListing,
    ShippingZone,
)
from saleor.warehouse.models import Warehouse


UPSERT_BUSINESS_PARTNER_MUTATION = """
    mutation upsertBusinessPartner($card_code: String!){
        upsertBusinessPartner(sapBpCode: $card_code){
            errors{
                field
                message
            }
        }
    }
"""

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


@pytest.fixture
def price_list_cache():
    return {
        "1": "MSRP",
        "2": "Dealer",
        "3": "Preferred",
        "4": "Preferred Plus",
        "5": "Elite",
        "6": "Distributor",
        "7": "Strategic Partner",
        "8": "Car Dealer Direct",
        "9": "Staub",
        "10": "RT",
        "11": "MESA Gold",
        "12": "Best Buy",
        "13": "RPM Dealer",
        "14": "RPM Program",
        "15": "PRM Distributor",
        "16": "RPM MESA Gold",
        "17": "RPM MESA Platinum",
        "18": "RPM Strategic Partner",
        "19": "Segi Warranty",
        "20": "Special 3",
        "21": "Special 4",
        "22": "Special 5",
        "23": "Special 6",
        "24": "Special 7",
        "25": "MESA Platinum",
        "26": "MAP",
        "27": "LISA",
    }


@pytest.fixture
def sap_shipping_types():
    return [
        {
            "Code": 1,
            "Name": "UPS Ground",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 2,
            "Name": "UPS Orange - 3 Day Air",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 3,
            "Name": "UPS Blue - 2nd Day Air",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 4,
            "Name": "UPS Red - Next Day Air",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 5,
            "Name": "UPS Freight_LTL",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 6,
            "Name": "LTL Freight",
            "Website": "Freight Company",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 7,
            "Name": "BBY SDF Ground",
            "Website": "610T3T",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 8,
            "Name": "BBY SDF Blue - 2nd Day Air",
            "Website": "610T3T",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 9,
            "Name": "BBY SDF Red - Next Day Air",
            "Website": "610T3T",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 10,
            "Name": "BBY SDF Ground - Signature Required",
            "Website": "610T3T",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 11,
            "Name": "BBY SDF Red - Signature Required",
            "Website": "610T3T",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 12,
            "Name": "UPS Ground BBY",
            "Website": "7W405A Bill to Third Party",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 13,
            "Name": "UPS Freight BBY",
            "Website": "7W405A Bill to Third Party",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 14,
            "Name": "Standard Ground",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 15,
            "Name": "Worldwide Expedited - 2nd Day Air",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 16,
            "Name": "Worldwide Express- Next Day Air",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 17,
            "Name": "Worldwide Saver - Express",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 18,
            "Name": "Worldwide Express Freight - Next Day Air",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 19,
            "Name": "Will Call",
            "Website": "",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 20,
            "Name": "UPS_GND",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 23,
            "Name": "UPS_Ground sender",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 24,
            "Name": "UPS Express Saver",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 25,
            "Name": "UPS Red Saturday Delivery - Next Day Air",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 26,
            "Name": "BBY SDF Blue - Signature Required",
            "Website": "610T3T",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 27,
            "Name": "UPS Ground with Freight Pricing",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 28,
            "Name": "UPS Mail Innovations",
            "Website": "7W405A",
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
        {
            "Code": 29,
            "Name": "Firstech Delivery Truck - Car Toys",
            "Website": None,
            "U_NWR_SerType": None,
            "U_NWR_CarType": None,
        },
    ]


@pytest.fixture
def shipping_methods():
    """Note the TrnspCode is being cast as a string because the shipping type migration
    script creates these methods using the graphql mutation for creating shipping
    methods, and that endpoint casts the private metadata fields into strings.
    """
    return [
        {
            "name": "Flat Rate",
            "type": "PRICE",
            "prices": [{"price": 0.00}],
            "privateMetadata": {"TrnspCode": "14", "TrnspName": "Standard Ground"},
        },
        {
            "name": "UPS Ground",
            "type": "PRICE",
            "prices": [
                {
                    "price": 12.50,
                    "minimumOrderPrice": 0.00,
                    "maximumOrderPrice": 249.99,
                },
                {
                    "price": 0.00,
                    "minimumOrderPrice": 250.00,
                },
            ],
            "privateMetadata": {"TrnspCode": "1", "TrnspName": "UPS Ground"},
        },
        {
            "name": "UPS 2-Day",
            "type": "PRICE",
            "prices": [
                {
                    "price": 17.50,
                    "minimumOrderPrice": 0.00,
                    "maximumOrderPrice": 249.99,
                },
                {
                    "price": 50.00,
                    "minimumOrderPrice": 250.00,
                    "maximumOrderPrice": 999.99,
                },
                {
                    "price": 80.00,
                    "minimumOrderPrice": 1000.00,
                    "maximumOrderPrice": 1999.99,
                },
                {
                    "price": 150.00,
                    "minimumOrderPrice": 2000.00,
                    "maximumOrderPrice": 2999.99,
                },
                {
                    "price": 0.00,
                    "minimumOrderPrice": 3000.00,
                },
            ],
            "privateMetadata": {
                "TrnspCode": "3",
                "TrnspName": "UPS Blue - 2nd Day Air",
            },
        },
        {
            "name": "UPS Next Day",
            "type": "PRICE",
            "prices": [
                {
                    "price": 30.00,
                    "minimumOrderPrice": 0.00,
                    "maximumOrderPrice": 249.99,
                },
                {
                    "price": 100.00,
                    "minimumOrderPrice": 250.00,
                    "maximumOrderPrice": 999.99,
                },
                {
                    "price": 160.00,
                    "minimumOrderPrice": 1000.00,
                    "maximumOrderPrice": 1999.99,
                },
                {
                    "price": 250.00,
                    "minimumOrderPrice": 2000.00,
                    "maximumOrderPrice": 2999.99,
                },
                {
                    "price": 0.00,
                    "minimumOrderPrice": 3000.00,
                },
            ],
            "privateMetadata": {
                "TrnspCode": "4",
                "TrnspName": "UPS Red - Next Day Air",
            },
        },
        {
            "name": "Local Pickup",
            "type": "PRICE",
            "prices": [{"price": 0.00}],
            "privateMetadata": {"TrnspCode": "19", "TrnspName": "Will Call"},
        },
        {
            "name": "CUSTOM SAP SHIPPING",
            "type": "PRICE",
            "prices": [{"price": 0.00}],
        },
    ]


@pytest.fixture
def inside_sales_reps():
    """Include this fixture in your test to create our internal sales reps"""
    inside_sales_rep_map = {
        "Danny": "dfellers@compustar.com",
        "Rob": "rsanden@compustar.com",
        "Jason": "jkaminski@compustar.com",
        "Justin R.": "jriego@compustar.com",
        "Brian": "bshaw@compustar.com",
        "Tanner": "twilson@compustar.com",
    }
    # Create the inside sales rep user accounts
    for name, email in inside_sales_rep_map.items():
        first_name = last_name = ""
        name_list = name.split()
        try:
            first_name = name_list[0]
            last_name = name_list[1]
        except IndexError:
            pass

        user = User.objects.create_user(
            first_name=first_name, last_name=last_name, email=email, is_staff=True
        )
        SAPSalesManager.objects.create(name=name, user=user)


@pytest.fixture
def ecommerce_basic_setup(
    sap_shipping_types,
    shipping_methods,
    inside_sales_reps,
    staff_api_client,
    permission_manage_users,
):
    """Creates a basic e-commerce setup consisting of
    - The dealer channel
    - The X1-LTE product and variant
    - The X1-LTEMax product and variant
    - All shipping methods and types
    - The Kent warehouse
    - The US shipping zone
    """

    def create_product(product_type, name, sku, price, channel):
        product = Product.objects.create(
            name=name, product_type=product_type, slug=name.lower()
        )

        product_variant = ProductVariant.objects.create(
            sku=sku,
            product=product,
            track_inventory=True,
        )

        ProductVariantChannelListing.objects.create(
            currency="USD",
            price_amount=price,
            channel=channel,
            variant=product_variant,
        )

        yesterday = timezone.now() - timedelta(days=1)

        ProductChannelListing.objects.create(
            publication_date=yesterday.date(),
            available_for_purchase=yesterday.date(),
            is_published=True,
            channel=channel,
            product=product,
            currency="USD",
            visible_in_listings=True,
        )

    channel = Channel.objects.create(
        name="Dealer",
        is_active=True,
        slug="dealer",
        currency_code="USD",
        default_country="US",
    )

    product_type = ProductType.objects.create(
        name="Drone Module",
        has_variants=False,
        is_shipping_required=True,
        weight=0,
        is_digital=False,
        slug="drone-module",
    )

    create_product(
        product_type,
        name="DR-X1 LTE, Cell + GPS, BG96MC-128-SGNS",
        sku="X1-LTE",
        price=90,
        channel=channel,
    )
    create_product(
        product_type,
        name="DR-X1MAX LTE, Cell, GPS, BLE, Sensors and Back-up batt BG96MC-128-SGNS",
        sku="X1MAX-LTE",
        price=90,
        channel=channel,
    )

    warehouse_address = Address.objects.create(
        street_address_1="21903 68th Avenue South",
        city="KENT",
        postal_code=98032,
        country="US",
        country_area="WA",
    )
    warehouse = Warehouse.objects.create(
        name="Kent, WA", slug="kent-wa", address=warehouse_address
    )
    shipping_zone = ShippingZone.objects.create(
        name="USA",
        countries=["US"],
    )
    shipping_zone.channels.add(channel)
    warehouse.shipping_zones.add(shipping_zone)

    for sap_shipping_method in shipping_methods:
        for price in sap_shipping_method["prices"]:
            shipping_method = ShippingMethod.objects.create(
                name=sap_shipping_method["name"],
                type="price",
                minimum_order_weight=0,
                shipping_zone=shipping_zone,
                private_metadata=sap_shipping_method.get("privateMetadata", {}),
            )

            ShippingMethodChannelListing.objects.create(
                shipping_method=shipping_method,
                channel=channel,
                price_amount=price["price"],
                currency="USD",
                minimum_order_price_amount=price.get("minimumOrderPrice", 0),
                maximum_order_price_amount=price.get("maximumOrderPrice"),
            )

    # Create a user that will act as an outside sales rep. When creating a new test that
    # uses VCR you may need to manually redact the email address of any real sales reps
    # that belong to a business partner and replace it with this or another email.
    User.objects.create_user(email="outside_sales_person@example.com")


@pytest.fixture
def sap_plugin(settings):
    """Include this fixture if you need the SAP plugin in your test"""
    settings.PLUGINS = ["saleor.plugins.sap_orders.plugin.SAPPlugin"]

    configuration = [
        {"name": "Username", "type": "String", "value": "test"},
        {"name": "Password", "type": "Password", "value": "test"},
        {"name": "Database", "type": "String", "value": "test"},
        {"name": "SAP Service Layer URL", "type": "String", "value": "https://api.myfirstech.com:50000/b1s/v1/"},
        {"name": "SSL Verification", "type": "Boolean", "value": False},
    ]

    PluginConfiguration.objects.create(
        identifier=SAPPlugin.PLUGIN_ID,
        name=SAPPlugin.PLUGIN_NAME,
        active=True,
        configuration=configuration,
    )
    manager = get_plugins_manager()

    sap_plugin = manager.get_plugin(plugin_id="firstech.sap")
    sap_plugin.sync_to_SAP = False

    return sap_plugin


@pytest.fixture
def business_partner(staff_api_client, permission_manage_users):
    """Include this fixture if you need a business partner in your test."""
    variables = {"card_code": "RIAN"}
    staff_api_client.post_graphql(
        UPSERT_BUSINESS_PARTNER_MUTATION,
        variables=variables,
        permissions=[permission_manage_users],
        check_no_permissions=False,
    )
