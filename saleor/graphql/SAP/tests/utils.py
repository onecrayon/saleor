from saleor.account.models import Address


def assert_address_match(address1: Address, address2: Address):
    """Used to check that two address objects are the same. We could loop over all the
    attributes in an address object, but we only care about the fields listed below"""
    assert address1.company_name.lower() == address2.company_name.lower()
    assert address1.street_address_1.lower() == address2.street_address_1.lower()
    assert address1.street_address_2.lower() == address2.street_address_2.lower()
    assert address1.city.lower() == address2.city.lower()
    assert address1.country_area.lower() == address2.country_area.lower()
    assert address1.country.code.lower() == address2.country.code.lower()
    assert address1.postal_code.lower() == address2.postal_code.lower()
