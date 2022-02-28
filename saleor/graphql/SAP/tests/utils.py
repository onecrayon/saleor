from saleor.account.models import Address


def assert_address_match(address1: Address, address2: Address):
    """Used to check that two address objects are the same. We could loop over all the
    attributes in an address object, but we only care about the fields listed below"""
    assert address1.company_name == address2.company_name
    assert address1.street_address_1 == address2.street_address_1
    assert address1.street_address_2 == address2.street_address_2
    assert address1.city == address2.city
    assert address1.country_area == address2.country_area
    assert address1.country.code == address2.country.code
    assert address1.postal_code == address2.postal_code
