from dataclasses import dataclass
from typing import TYPE_CHECKING

import requests
from django.core.cache import caches
from django.core.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    from saleor.plugins.manager import PluginsManager
    from saleor.plugins.sap_orders.plugin import SAPPlugin

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


def get_sap_plugin_or_error(manager: "PluginsManager"):
    """Returns the SAP plugin if it is configured correctly, or returns Error.

    :param manager: An instance of a plugins manager. Usually can be obtained through
        a mutation's info.context.plugins attribute.

    :returns: An instance of the SAPPlugin class.
    """
    sap_plugin: SAPPlugin = manager.get_plugin(plugin_id="firstech.sap")
    if not sap_plugin or not sap_plugin.active:
        # the SAP plugin is inactive or doesn't exist
        raise ImproperlyConfigured("SAP Plugin is not active")

    for config in sap_plugin.configuration:
        if not config["value"] and config["value"] is not False:
            # Raise error for any fields that are null or blank (explicitly False is ok)
            raise ImproperlyConfigured("SAP Plugin is not properly configured.")

    # Turn this flag to False so that we don't try to push changes to SAP while we are
    # upserting those objects from SAP. Otherwise while we are updating saleor objects
    # with information from SAP, the plugin manager will be triggered and try to update
    # SAP.
    sap_plugin.sync_to_SAP = False

    return sap_plugin
