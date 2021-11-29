from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django_prices.models import MoneyField, TaxedMoneyField

from firstech.permissions import SAPStaffPermissions, SAPCustomerPermissions
from firstech.SAP import DroneDistribution, ReturnType, ReturnStatus
from saleor.account.models import Address, User
from saleor.channel.models import Channel
from saleor.checkout import AddressType
from saleor.order.models import Order
from saleor.product.models import ProductVariant
from saleor.shipping.models import ShippingMethod


DEFAULT_CHANNEL_ID = 1


class BusinessPartner(models.Model):
    addresses = models.ManyToManyField(
        Address,
        blank=True,
        related_name="business_partner_addresses",
        through="BusinessPartnerAddresses",
    )
    account_balance = models.DecimalField(
        decimal_places=2,
        max_digits=10,
        null=True,
        blank=True,
    )
    account_is_active = models.BooleanField(default=True)
    account_purchasing_restricted = models.BooleanField(default=False)
    company_name = models.CharField(max_length=256, blank=True, null=True)
    company_url = models.CharField(max_length=256, blank=True, null=True)
    credit_limit = models.DecimalField(
        decimal_places=2, max_digits=10, null=True, blank=True
    )
    customer_type = models.CharField(max_length=256, blank=True, null=True)
    debit_limit = models.DecimalField(
        decimal_places=2, max_digits=10, null=True, blank=True
    )
    # Setting default shipping and billing addresses here mimics the design of Accounts
    # and billing/shipping addresses
    default_shipping_address = models.ForeignKey(
        Address, related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )
    default_billing_address = models.ForeignKey(
        Address, related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )
    inside_sales_rep = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL
    )
    internal_ft_notes = models.TextField(blank=True, null=True)
    outside_sales_rep = models.ManyToManyField(
        User, blank=True, related_name="outside_sales_reps", through="OutsideSalesRep"
    )
    payment_terms = models.CharField(max_length=256, blank=True, null=True)
    channel = models.ForeignKey(
        Channel,
        on_delete=models.PROTECT,
        null=False,
        blank=False,
        default=DEFAULT_CHANNEL_ID,
    )
    sales_manager = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_manager",
    )
    sap_bp_code = models.CharField(max_length=256, blank=True, null=True, unique=True)
    # The shipping preference is the name of the shipping method from SAP. The exact
    # `ShippingMethod` used on an order depends on the value of the order.
    shipping_preference = models.CharField(max_length=256, blank=True, null=True)
    sync_partner = models.BooleanField(default=True)
    warranty_preference = models.CharField(max_length=256, blank=True, null=True)

    @property
    def company_contacts(self):
        """Returns a queryset of users linked to this business partner. This only
        includes installer/dealer accounts, and does not include any linked sales reps
        or sales managers."""
        return User.objects.filter(sapuserprofile__business_partners=self)


class ApprovedBrands(models.Model):
    business_partner = models.OneToOneField(BusinessPartner, on_delete=models.CASCADE)
    momento = models.BooleanField(default=True)
    tesa = models.BooleanField(default=True)
    idatalink = models.BooleanField(default=True)
    maestro = models.BooleanField(default=True)
    compustar = models.BooleanField(default=False)
    compustar_pro = models.BooleanField(default=False)
    ftx = models.BooleanField(default=False)
    arctic_start = models.BooleanField(default=False)
    compustar_mesa_only = models.BooleanField(default=False)
    replacements = models.BooleanField(default=True)


class SAPUserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    date_of_birth = models.DateField(null=True, blank=True)
    # Most of the time a user will only be associated with 1 business partner, but there
    # are some examples where a user can have more.
    business_partners = models.ManyToManyField(
        BusinessPartner,
        related_name="sapuserprofiles",
        blank=True,
    )
    middle_name = models.CharField(max_length=256, blank=True, null=True)

    class Meta:
        permissions = (
            (SAPCustomerPermissions.DRONE_ACTIVATION.codename, "Can activate drone."),
            (SAPCustomerPermissions.VIEW_PRODUCTS.codename, "Can view products."),
            (
                SAPCustomerPermissions.PURCHASE_PRODUCTS_B2C.codename,
                "Can purchase products B2C."
            ),
            (SAPCustomerPermissions.VIEW_WIRING.codename, "Can view wiring diagrams."),
            (SAPCustomerPermissions.VIEW_DOCUMENTS.codename, "Can view documents."),
            (
                SAPCustomerPermissions.VIEW_DRONE_REWARDS.codename,
                "Can view Drone dealer rewards.",
            ),
            (
                SAPCustomerPermissions.VIEW_PROFILE.codename,
                "Can view SAP user and business partner profiles.",
            ),
            (
                SAPCustomerPermissions.PURCHASE_PRODUCTS_B2B.codename,
                "Can purchase products B2B.",
            ),
            (
                SAPCustomerPermissions.MANAGE_BP_ORDERS.codename,
                "Can manage orders for business partner."
            ),
            (
                SAPCustomerPermissions.VIEW_ACCOUNT_BALANCE.codename,
                "Can view business partner account balance."
            ),
            (SAPCustomerPermissions.REPORTING.codename, "Can create reports."),
            (
                SAPCustomerPermissions.INVITE_NEW_INSTALLERS.codename,
                "Can invite new installers to business partner.",
            ),
            (
                SAPCustomerPermissions.MANAGE_DRONE_BILLING_METHODS.codename,
                "Can manage drone billing methods.",
            ),
            (
                SAPCustomerPermissions.MANAGE_BILLING_METHODS.codename,
                "Can manage billing methods."
            ),
            (
                SAPCustomerPermissions.MANAGE_LINKED_INSTALLERS.codename,
                "Can modify linked installers.",
            ),
            (SAPCustomerPermissions.MANAGE_CONTRACT.codename, "Can manage contract."),
            (
                SAPCustomerPermissions.ACCESS_TO_LINKED_ACCOUNTS.codename,
                "Can view linked accounts.",
            ),
            (SAPCustomerPermissions.VIEW_BACKORDERS.codename, "Can view backorders."),
            (
                SAPCustomerPermissions.PLACE_ORDERS_FOR_LINKED_ACCOUNTS.codename,
                "Can place orders for linked accounts.",
            ),
            (
                SAPStaffPermissions.DEFINE_PAYMENT_METHODS.codename,
                "Can define new payment methods.",
            ),
            (
                SAPStaffPermissions.DEFINE_BRAND_ACCESS.codename,
                "Can define brand access.",
            ),
            (
                SAPStaffPermissions.PLACE_ORDERS_FOR_DEALER.codename,
                "Can place orders for a dealer.",
            ),
            (
                SAPStaffPermissions.BACKORDER_MANAGEMENT.codename,
                "Can manage backorders.",
            ),
            (
                SAPStaffPermissions.VOLUME_INCENTIVE_REBATES.codename,
                "Can manage volume incentive rebates.",
            ),
            (
                SAPStaffPermissions.DEFINE_DEALER_ROLES.codename,
                "Can define dealer roles.",
            ),
            (
                SAPStaffPermissions.DISABLE_DEALER_ACCOUNT.codename,
                "Can disable dealer accounts.",
            ),
            (
                SAPStaffPermissions.GENERATE_PAST_DUE_NOTICE.codename,
                "Can generate past due notices.",
            ),
            (
                SAPStaffPermissions.MANAGE_ACCOUNT_STATEMENTS.codename,
                "Can manage account statements.",
            ),
            (
                SAPStaffPermissions.INSIDE_SALES_REP_VIEW.codename,
                "Can view business partners as an inside sales rep (all fields)."
            ),
        )


class DroneRewardsProfile(models.Model):
    # Making this its own table to anticipate future expansion and to match what's
    # outlined in the spec.
    business_partner = models.OneToOneField(BusinessPartner, on_delete=models.CASCADE)
    enrolled = models.BooleanField(default=False)
    onboarded = models.BooleanField(default=False)
    distribution = models.CharField(
        choices=DroneDistribution.CHOICES,
        max_length=20,
        default=DroneDistribution.STRIPE,
    )


class BusinessPartnerAddresses(models.Model):
    # Intermediary table for business partner to address m2m relationship
    business_partner = models.ForeignKey(BusinessPartner, on_delete=models.CASCADE)
    address = models.ForeignKey(Address, on_delete=models.CASCADE)
    type = models.CharField(
        choices=AddressType.CHOICES, max_length=10, default=AddressType.SHIPPING
    )
    # SAP assigns an id to addresses that is unique with the business partner. We can
    # use this to track if an address is new/updated/removed
    row_number = models.IntegerField(null=True)

    class Meta:
        unique_together = ["business_partner", "row_number"]


class OutsideSalesRep(models.Model):
    name = models.CharField(max_length=256, blank=False, null=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    business_partner = models.ForeignKey(BusinessPartner, on_delete=models.CASCADE)


class SAPReturn(models.Model):
    """This is a really basic table for holding return info that we receive from SAP.
    These returns aren't created through myFirstech or the dashboard."""

    doc_entry = models.IntegerField(unique=True, null=True, blank=True)
    # This is the creation date of the SAP return document, not the timestamp for being
    # added to this table
    sap_create_date = models.DateField(blank=True, null=True)
    business_partner = models.ForeignKey(BusinessPartner, on_delete=models.CASCADE)
    order = models.ForeignKey(Order, blank=True, null=True, on_delete=models.SET_NULL)
    remarks = models.TextField(blank=True, null=True)
    po_number = models.CharField(max_length=255, blank=True, null=True)

    currency = models.CharField(
        max_length=settings.DEFAULT_CURRENCY_CODE_LENGTH,
    )

    total_net_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        default=0,
    )

    total_net = MoneyField(amount_field="total_net_amount", currency_field="currency")

    total_gross_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        default=0,
    )

    total_gross = MoneyField(
        amount_field="total_gross_amount", currency_field="currency"
    )

    total = TaxedMoneyField(
        net_amount_field="total_net_amount",
        gross_amount_field="total_gross_amount",
        currency_field="currency",
    )

    return_type = models.CharField(
        max_length=32, default=ReturnType.EXCHANGE, choices=ReturnType.CHOICES
    )

    status = models.CharField(
        max_length=32, default=ReturnStatus.PENDING, choices=ReturnStatus.CHOICES
    )

    rma_base = models.CharField(max_length=32, null=True, blank=True, db_index=True)

    rma_number = models.CharField(max_length=32, unique=True, null=True, blank=True)

    billing_address = models.ForeignKey(
        "account.Address",
        related_name="+",
        editable=False,
        null=True,
        on_delete=models.SET_NULL,
    )

    shipping_address = models.ForeignKey(
        "account.Address",
        related_name="+",
        editable=False,
        null=True,
        on_delete=models.SET_NULL,
    )
    # There's no need to link to the actual shipping method object which is dependent
    # on the value of the order, the shipping address, channel, etc. We will record the
    # name of the shipping method that should be used in the event of an exchange. The
    # exchange will be sent using a new order created from information in this return.
    # At that time the exact shipping method can be determined.
    shipping_method_name = models.CharField(
        max_length=255, null=True, default=None, blank=True, editable=False
    )

    customer_note = models.TextField(blank=True, default="")


class SAPReturnLine(models.Model):
    sap_return = models.ForeignKey(
        SAPReturn, related_name="lines", on_delete=models.CASCADE
    )
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT)
    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    currency = models.CharField(
        max_length=settings.DEFAULT_CURRENCY_CODE_LENGTH,
    )
    unit_price_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        blank=True,
        null=True,
    )
    unit_price = MoneyField(amount_field="unit_price_amount", currency_field="currency")


class SAPCreditMemo(models.Model):
    """This is a really basic table for holding credit memo info that we receive from
    SAP. These documents aren't created through myFirstech or the dashboard."""

    doc_entry = models.IntegerField(unique=True)
    # This is the creation date of the SAP return document, not the timestamp for being
    # added to this table
    create_date = models.DateField(blank=True, null=True)
    business_partner = models.ForeignKey(BusinessPartner, on_delete=models.CASCADE)
    order = models.ForeignKey(Order, blank=True, null=True, on_delete=models.SET_NULL)
    remarks = models.TextField(blank=True, null=True)
    purchase_order = models.CharField(max_length=255, blank=True, null=True)

    currency = models.CharField(
        max_length=settings.DEFAULT_CURRENCY_CODE_LENGTH,
    )

    total_net_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        default=0,
    )

    total_net = MoneyField(amount_field="total_net_amount", currency_field="currency")

    total_gross_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        default=0,
    )

    total_gross = MoneyField(
        amount_field="total_gross_amount", currency_field="currency"
    )

    total = TaxedMoneyField(
        net_amount_field="total_net_amount",
        gross_amount_field="total_gross_amount",
        currency_field="currency",
    )

    refunded = models.BooleanField(default=False)
    status = models.CharField(max_length=255, blank=True, null=True)


class SAPCreditMemoLine(models.Model):
    sap_credit_memo = models.ForeignKey(
        SAPCreditMemo, related_name="lines", on_delete=models.CASCADE
    )
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT)
    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    currency = models.CharField(
        max_length=settings.DEFAULT_CURRENCY_CODE_LENGTH,
    )
    unit_price_amount = models.DecimalField(
        max_digits=settings.DEFAULT_MAX_DIGITS,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        blank=True,
        null=True,
    )
    unit_price = MoneyField(amount_field="unit_price_amount", currency_field="currency")


class SAPSalesManager(models.Model):
    """Business partners point to sales managers and inside sales reps in SAP. However,
    instead of being linked via an id or email address, they are linked via whatever
    name they have in the SAP database. So this table is simply to associate a name
    to a specific user object."""

    name = models.CharField(max_length=20, unique=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
