from django.contrib.postgres.fields import ArrayField
from django.db import models

from saleor.account.models import Address, User
from saleor.channel.models import Channel
from saleor.checkout import AddressType

from . import DroneDistribution


DEFAULT_CHANNEL_ID = 1


class BusinessPartner(models.Model):
    addresses = models.ManyToManyField(
        Address,
        blank=True,
        related_name="business_partner_addresses",
        through="BusinessPartnerAddresses"
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
        decimal_places=2,
        max_digits=10,
        null=True,
        blank=True
    )
    customer_type = models.CharField(max_length=256, blank=True, null=True)
    debit_limit = models.DecimalField(
        decimal_places=2,
        max_digits=10,
        null=True,
        blank=True
    )
    # Setting default shipping and billing addresses here mimics the design of Accounts
    # and billing/shipping addresses
    default_shipping_address = models.ForeignKey(
        Address, related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )
    default_billing_address = models.ForeignKey(
        Address, related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )
    inside_sales_rep = models.CharField(max_length=256, blank=True, null=True)
    internal_ft_notes = models.TextField(blank=True, null=True)
    outside_sales_rep = models.CharField(max_length=256, blank=True, null=True)
    outside_sales_rep_emails = ArrayField(
        base_field=models.EmailField(),
        blank=True,
        null=True
    )
    payment_terms = models.CharField(max_length=256, blank=True, null=True)
    channel = models.ForeignKey(
        Channel,
        on_delete=models.PROTECT,
        null=False,
        blank=False,
        default=DEFAULT_CHANNEL_ID,
    )
    sales_manager = models.CharField(max_length=256, blank=True, null=True)
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
    business_partner = models.ForeignKey(
        BusinessPartner, related_name="business_partner", null=True, blank=True,
        on_delete=models.SET_NULL
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
        choices=AddressType.CHOICES,
        max_length=10,
        default=AddressType.SHIPPING
    )
