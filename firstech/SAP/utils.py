from django.core.cache import caches
import requests
from saleor import settings


def get_sap_cookies():
    """Either returns the session cookies for our connection to SAP service layer if
    they exist, or logs in to SAP service layer and caches the session cookies."""
    cache = caches["default"]
    if cookies := cache.get("sap_login_cookies"):
        return cookies

    response = requests.post(
        url=settings.SAP_SERVICE_LAYER_URL + "Login",
        json={
            "UserName": settings.SAP_SERVICE_LAYER_USERNAME,
            "Password": settings.SAP_SERVICE_LAYER_PASSWORD,
            "CompanyDB": settings.SAP_SERVICE_LAYER_DB,
        },
        # TODO: TURN SSL VERIFICATION BACK ON
        verify=False,
    )
    # Cookies are kept for 30 minutes
    cache.set("sap_login_cookies", response.cookies, timeout=60 * 30)
    return response.cookies
