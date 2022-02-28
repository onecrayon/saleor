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


def get_sap_plugin_or_error(manager: "PluginsManager", remove_from_manager=True):
    """Returns the SAP plugin if it is configured correctly, or returns Error. The
    remove_from_manager parameter can be used to remove the sap plugin from the plugin
    manager's list of plugins. This is useful when we are updating existing objects in
    saleor, and don't want to trigger a redundant and cyclical update. For example,
    when updating an existing order using the UpsertSAPOrder mutation, the
    "order_updated" plugin method will be triggered when we save the Order. This would
    cause the SAP plugin to send a PATCH request back to SAP even though our changes
    are coming *from* SAP. By removing the plugin from the manager, those methods can't
    be triggered.

    :param manager: An instance of a plugins manager. Usually can be obtained through
        a mutation's info.context.plugins attribute.
    :param remove_from_manager: Whether or not to "pop" the plugin from the manager's
        list of plugins.
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

    if remove_from_manager:
        try:
            manager.all_plugins.remove(sap_plugin)
        except ValueError:
            pass
        try:
            manager.global_plugins.remove(sap_plugin)
        except ValueError:
            pass
        for channel, plugin_list in manager.plugins_per_channel.items():
            try:
                plugin_list.remove(sap_plugin)
            except ValueError:
                pass

    return sap_plugin
