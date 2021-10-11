from dataclasses import dataclass

import requests
from django.core.cache import caches


@dataclass
class SAPServiceLayerConfiguration:
    username: str
    password: str
    database: str
    url: str
    verify_ssl: bool


def is_truthy(value):
    return value in (True, 1, "True", "true", "TRUE")


def get_sap_cookies(config: SAPServiceLayerConfiguration, skip_cache=False):
    """Either returns the session cookies for our connection to SAP service layer if
    they exist, or logs in to SAP service layer and caches the session cookies."""
    cache = caches["default"]
    if not skip_cache:
        if cookies := cache.get("sap_login_cookies"):
            return cookies

    response = requests.post(
        url=config.url + "Login",
        json={
            "UserName": config.username,
            "Password": config.password,
            "CompanyDB": config.database,
        },
        verify=config.verify_ssl,
    )
    # Cookies are kept for 29 minutes (1 minute less than they are good for)
    cache.set("sap_login_cookies", response.cookies, timeout=60 * 29)
    return response.cookies


def get_price_list_cache(config: SAPServiceLayerConfiguration) -> dict:
    """Returns a dict for getting the name of an SAP price list from its number.
    For example: {1: "MSRP"}. This is useful because SAP service layer requests will
    give a price list by its number rather than its name. This dict is cached in redis
    since it is highly unlikely that price lists will be added or updated often. The
    cache will be refreshed once per day as specified in the timeout parameter.
     """
    cache = caches["default"]
    if price_list_cache := cache.get("price_list_cache"):
        return price_list_cache

    # Get all of the price lists names / slugs
    skip = 0
    price_list_cache = {}
    while skip is not None:
        price_lists = requests.get(
            url=config.url + f"PriceLists?$skip={skip}",
            cookies=get_sap_cookies(config),
            headers={"B1S-ReplaceCollectionsOnPatch": "true"},
            verify=config.verify_ssl,
        ).json()
        for price_list in price_lists["value"]:
            price_list_cache[price_list["PriceListNo"]] = price_list[
                "PriceListName"
            ]

        if "odata.nextLink" in price_lists:
            skip += 20
        else:
            skip = None

    cache.set("price_list_cache", price_list_cache, timeout=60 * 60 * 24)
    return price_list_cache
