from dataclasses import dataclass
from django.core.cache import caches
import requests


@dataclass
class SAPServiceLayerConfiguration:
    username: str
    password: str
    database: str
    url: str


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
        # TODO: TURN SSL VERIFICATION BACK ON
        verify=False,
    )
    # Cookies are kept for 30 minutes
    cache.set("sap_login_cookies", response.cookies, timeout=60 * 30)
    return response.cookies
