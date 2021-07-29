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


def get_sap_cookies(config: SAPServiceLayerConfiguration):
    """Either returns the session cookies for our connection to SAP service layer if
    they exist, or logs in to SAP service layer and caches the session cookies."""
    cache = caches["default"]
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
