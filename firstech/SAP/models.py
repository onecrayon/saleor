from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django_prices.models import MoneyField, TaxedMoneyField

from saleor.account.models import Address, User
from saleor.channel.models import Channel
from saleor.checkout import AddressType
from saleor.order.models import Order
from saleor.product.models import ProductVariant

from . import DroneDistribution

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
    shipping_preference = models.CharField(max_length=256, blank=True, null=True)
    sync_partner = models.BooleanField(default=True)
    warranty_preference = models.CharField(max_length=256, blank=True, null=True)


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
    is_company_owner = models.BooleanField(default=False)
    # Most of the time a user will only be associated with 1 business partner, but there
    # are some examples where a user can have more.
    business_partners = models.ManyToManyField(
        BusinessPartner,
        related_name="sapuserprofiles",
        blank=True,
    )
    middle_name = models.CharField(max_length=256, blank=True, null=True)


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


class OutsideSalesRep(models.Model):
    name = models.CharField(max_length=256, blank=False, null=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    business_partner = models.ForeignKey(BusinessPartner, on_delete=models.CASCADE)


class SAPReturn(models.Model):
    """This is a really basic table for holding return info that we receive from SAP.
    These returns aren't created through myFirstech or the dashboard."""

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


class SAPReturnLine(models.Model):
    sap_return = models.ForeignKey(
        SAPReturn, related_name="lines", on_delete=models.CASCADE
    )
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT)
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
