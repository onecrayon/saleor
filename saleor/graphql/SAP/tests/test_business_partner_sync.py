from typing import List
from unittest.mock import patch

from firstech.SAP.models import (
    ApprovedBrands,
    BusinessPartner,
    BusinessPartnerAddresses,
    OutsideSalesRep,
    SAPSalesManager,
)
from saleor.account.models import Address, UserManager
from saleor.channel.models import Channel
from saleor.checkout import AddressType
from saleor.graphql.SAP.tests.utils import assert_address_match
from saleor.graphql.tests.utils import get_graphql_content
from saleor.plugins.sap_orders.plugin import SAPPlugin
from saleor.shipping.models import ShippingMethod

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


@patch.object(SAPPlugin, "fetch_sales_person")
@patch.object(SAPPlugin, "fetch_payment_terms")
@patch.object(SAPPlugin, "fetch_shipping_type")
@patch.object(SAPPlugin, "fetch_business_partner")
@patch.object(SAPPlugin, "fetch_order")
def test_business_partner_sync(
    fetch_order_mock,
    fetch_business_partner_mock,
    fetch_shipping_type_mock,
    fetch_payment_terms_mock,
    fetch_sales_person_mock,
    staff_api_client,
    sap_plugin,
    permission_manage_users,
    sap_business_partner,
    updated_sap_business_partner,
    ecommerce_basic_setup,
):
    """Test that the `UpsertBusinessPartner` mutation correctly syncs data from SAP
    into Saleor."""

    def assert_business_partner_sync(bp: BusinessPartner, sap_business_partner: dict):
        # The addresses that were created in Saleor
        bp_addresses = BusinessPartnerAddresses.objects.filter(
            business_partner=bp
        ).order_by("row_number")

        # The addresses as given by SAP
        sap_addresses: List[dict] = sap_business_partner["BPAddresses"]
        # Sort the addresses by row number to match the address objects from the query
        sap_addresses = sorted(sap_addresses, key=lambda i: i["RowNum"])

        # If an address is deleted in SAP, we don't delete it in Saleor because we might
        # be using it for an order or something. So here we are just checking that all
        # of the sap addresses were created/updated.
        for sap_address in sap_addresses:
            for bp_address in bp_addresses:
                if sap_address["RowNum"] == bp_address.row_number:
                    if sap_address["AddressType"] == "bo_ShipTo":
                        shipping_type = AddressType.SHIPPING
                    else:
                        shipping_type = AddressType.BILLING

                    assert bp_address.type == shipping_type

                    assert_address_match(
                        bp_address.address,
                        Address(
                            company_name=sap_address["AddressName"] or "",
                            street_address_1=sap_address["Street"] or "",
                            street_address_2=sap_address["BuildingFloorRoom"] or "",
                            city=sap_address["City"] or "",
                            country_area=sap_address["State"] or "",
                            country=sap_address["Country"] or "",
                            postal_code=sap_address["ZipCode"] or "",
                        ),
                    )
                    break
            else:
                raise AssertionError(
                    f"The following SAP address was not synced: {sap_address}"
                )

        # TODO: there are several fields that look like "Balance", need to make sure we
        #  have the right one.
        assert bp.account_balance == sap_business_partner["CurrentAccountBalance"]
        # assert bp.account_is_active == (sap_bp["Active"] == "tYES")
        # assert bp.account_purchasing_restricted == (sap_bp["Active"] == "tYES")
        assert bp.company_name == sap_business_partner["CardName"]
        assert bp.company_url == sap_business_partner["Website"]
        assert bp.credit_limit == sap_business_partner["CreditLimit"]
        assert bp.customer_type == sap_business_partner["CompanyPrivate"]
        assert bp.debit_limit == sap_business_partner["MaxCommitment"]

        inside_sales_rep = SAPSalesManager.objects.filter(
            name=sap_business_partner["U_SalesSupport"]
        ).first()

        assert bp.inside_sales_rep == inside_sales_rep.user
        assert bp.internal_ft_notes == sap_business_partner["FreeText"]
        assert bp.payment_terms == sap_business_partner["payment_terms"]

        channel = Channel.objects.filter(
            slug=sap_business_partner["channel_slug"]
        ).first()
        assert bp.channel == channel

        sales_manager = SAPSalesManager.objects.filter(
            name=sap_business_partner["U_SalesManager"]
        ).first()
        assert bp.sales_manager == sales_manager.user

        shipping_method = ShippingMethod.objects.filter(
            private_metadata__TrnspCode=str(sap_business_partner["ShippingType"])
        ).first()
        assert bp.shipping_preference == shipping_method.private_metadata["TrnspName"]

        assert bp.sync_partner == (sap_business_partner["U_V33_SYNCB2B"] == "YES")
        assert bp.warranty_preference == sap_business_partner["U_Warranty"]

        for email in sap_business_partner["outside_sales_rep_emails"]:
            normalized_email = UserManager.normalize_email(email)
            assert OutsideSalesRep.objects.filter(
                user__email=normalized_email,
                name=sap_business_partner["outside_sales_rep_name"],
                business_partner=bp,
            ).exists()

        approved_brands = ApprovedBrands.objects.get(business_partner=bp)
        assert approved_brands.compustar == (
            sap_business_partner["U_V33_COMPUSTAR"] == "YES"
        )
        assert approved_brands.compustar_pro == (
            sap_business_partner["U_V33_PRODLR"] == "YES"
        )
        assert approved_brands.ftx == (sap_business_partner["U_V33_FTX"] == "YES")
        assert approved_brands.arctic_start == (
            sap_business_partner["U_V33_ARCSTART"] == "YES"
        )

        profiles = bp.sapuserprofiles.all().order_by("user__email")
        sap_contacts = sap_business_partner["ContactEmployees"]
        sap_contacts = sorted(sap_contacts, key=lambda i: i["E_Mail"])
        for contact, profile in zip(sap_contacts, profiles):
            normalized_email = UserManager.normalize_email(contact["E_Mail"])
            assert normalized_email == profile.user.email
            assert contact["FirstName"] == (profile.user.first_name or None)
            assert contact["LastName"] == (profile.user.last_name or None)
            assert contact["MiddleName"] == (profile.middle_name or None)

            birthday = None
            if profile.date_of_birth:
                birthday = profile.date_of_birth.strftime("%Y-%m-%d")

            assert contact["DateOfBirth"] == birthday

    fetch_business_partner_mock.return_value = sap_business_partner
    variables = {"card_code": "MOM"}
    response = staff_api_client.post_graphql(
        UPSERT_BUSINESS_PARTNER_MUTATION,
        variables=variables,
        permissions=[permission_manage_users],
        check_no_permissions=False,
    )
    content = get_graphql_content(response)
    bp = BusinessPartner.objects.get(sap_bp_code=sap_business_partner["CardCode"])
    assert_business_partner_sync(bp, sap_business_partner)

    fetch_business_partner_mock.return_value = updated_sap_business_partner
    response = staff_api_client.post_graphql(
        UPSERT_BUSINESS_PARTNER_MUTATION,
        variables=variables,
        permissions=[permission_manage_users],
        check_no_permissions=False,
    )
    content = get_graphql_content(response)
    bp.refresh_from_db()
    assert_business_partner_sync(bp, updated_sap_business_partner)
