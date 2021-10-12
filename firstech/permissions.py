from saleor.core.permissions import BasePermissionEnum, PERMISSIONS_ENUMS


class SAPCustomerPermissions(BasePermissionEnum):
    """Even though some of these permissions aren't strictly related to SAP, we are
    creating the permissions via the SAP User Profile model's Meta information.
    Therefore, they all need to have the SAP prefix since that is the app they are being
    created in."""
    # Customer/Installer/Dealer/Outside permissions
    DRONE_ACTIVATION = "SAP.drone_activation"
    VIEW_PRODUCTS = "SAP.view_products"
    PURCHASE_PRODUCTS_B2C = "SAP.purchase_products_b2c"

    VIEW_WIRING = "SAP.view_wiring"
    VIEW_DOCUMENTS = "SAP.view_documents"
    VIEW_DRONE_REWARDS = "SAP.view_drone_rewards"
    VIEW_PROFILE = "SAP.view_profile"

    PURCHASE_DRONE_SERVICE = "SAP.purchase_drone_service"
    PURCHASE_PRODUCTS_B2B = "SAP.purchase_products_b2b"

    MANAGE_BP_ORDERS = "SAP.manage_business_partner_orders"

    REPORTING = "SAP.manage_reporting"
    INVITE_NEW_INSTALLERS = "SAP.invite_installers"

    MANAGE_DRONE_BILLING_METHODS = "SAP.manage_drone_billing_methods"
    MANAGE_BILLING_METHODS = "SAP.manage_billing_methods"

    MANAGE_LINKED_INSTALLERS = "SAP.manage_linked_installers"
    MANAGE_CONTRACT = "SAP.manage_contract"

    ACCESS_TO_LINKED_ACCOUNTS = "SAP.access_linked_accounts"
    VIEW_BACKORDERS = "SAP.view_backorders"
    PLACE_ORDERS_FOR_LINKED_ACCOUNTS = "SAP.place_orders_for_linked_accounts"


class SAPStaffPermissions(BasePermissionEnum):
    # Staff permissions
    DEFINE_PAYMENT_METHODS = "SAP.define_payments_methods"
    DEFINE_BRAND_ACCESS = "SAP.define_brand_access"
    PLACE_ORDERS_FOR_DEALER = "SAP.place_orders_for_dealer"
    BACKORDER_MANAGEMENT = "SAP.manage_backorders"
    VOLUME_INCENTIVE_REBATES = "SAP.manage_volume_incentive_rebates"
    DEFINE_DEALER_ROLES = "SAP.define_dealer_roles"

    DISABLE_DEALER_ACCOUNT = "SAP.disable_dealer_account"
    GENERATE_PAST_DUE_NOTICE = "SAP.create_past_due_notice"
    MANAGE_ACCOUNT_STATEMENTS = "SAP.manage_account_statements"


# Add the new permissions to Saleor's existing list of permission classes so that
#  they appear with the others.
PERMISSIONS_ENUMS.extend(
    [
        SAPStaffPermissions,
        SAPCustomerPermissions,
    ]
)


def get_customer_permissions_enum_list():
    permissions_list = [
        (enum.name, enum.value)
        for enum in SAPCustomerPermissions
    ]
    return permissions_list
