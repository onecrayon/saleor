from dataclasses import dataclass
from dateutil.relativedelta import relativedelta
from typing import Optional, Union

from django.db import models, connections
from django.utils import timezone

from saleor.account.models import User, Address
from . import constants


class DroneUserProfile(models.Model):
    """This model stores additional user information that is relevant to both Drone IoT
    and Saleor"""

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    drone_user_id = models.IntegerField(unique=True)
    cognito_sub = models.CharField(
        max_length=100,
        blank=True,
        null=False
    )

    # We are keeping a copy of the drone user phone number because it is tied to the
    # cognito id token.
    #
    # WARNING: This phone number should not be used for billing/shipping info
    # for dealers/installers.
    id_phone_number = models.CharField(
        max_length=20,
        blank=False,
        null=False
    )
    latest_global_logout = models.DateTimeField(
        blank=True,
        null=True,
    )
    update_date = models.DateTimeField(auto_now=True)
    installer_id = models.IntegerField(unique=True, null=True)
    dealer_id = models.IntegerField(unique=False, null=True)
    dealer_retired_date = models.DateTimeField(blank=True, null=True)
    is_company_owner = models.BooleanField(null=True, default=None)

    def refresh_drone_profile(self, email: str = None):
        """Gets the latest and greatest user information from the Drone API. Updates the
        saleor user and/or drone_user_profile if any changes are detected. Only saves if
        there are changes to keep database writes to a minimum.

        :param email: Optional email string. If provided, this function
            will look up the drone profile with the provided email rather than the
            existing email attached to the drone user profile.
        """
        drone_user_info = DroneUser.get_user_from_drone(email or self.user.email)

        field_mappings = [
            (self.user, 'email', drone_user_info.email),
            (self.user, 'first_name', drone_user_info.first_name),
            (self.user, 'last_name', drone_user_info.last_name),
            (self.user, 'is_staff',
             drone_user_info.access_type == constants.FIRSTECH_ADMIN),
            (self, 'drone_user_id', drone_user_info.user_id),
            (self, 'cognito_sub', drone_user_info.cognito_sub),
            (self, 'id_phone_number', drone_user_info.id_phone_number),
            (self, 'latest_global_logout', drone_user_info.latest_global_logout),
            (self, 'installer_id', drone_user_info.installer_id),
            (self, 'dealer_id', drone_user_info.dealer_id),
            (self, 'dealer_retired_date', drone_user_info.dealer_retired_date),
            (self, 'is_company_owner', drone_user_info.is_company_owner),
        ]

        update_profile_fields = {'update_date'}
        update_user_fields = set()
        for model, attr, value in field_mappings:
            if getattr(model, attr) != value:
                setattr(model, attr, value)
                if model == self.user:
                    update_user_fields.add(attr)
                else:
                    update_profile_fields.add(attr)

        self.user.save(update_fields=update_user_fields)
        self.save(update_fields=update_profile_fields)


@dataclass
class DroneUser:
    """Represents a Drone User model as a data class to allow us to refer to fields
    using familiar syntax. Does not hold all the fields or methods of the real drone
    user model. Defining this in its own class also lets us use type hints"""
    user_id: int
    email: str
    cognito_sub: str
    id_phone_number: str

    first_name: str = ""
    last_name: str = ""
    access_type: str = None
    latest_global_logout: timezone.datetime = None
    installer_id: int = None
    dealer_id: int = None
    dealer_retired_date: timezone.datetime = None
    is_company_owner: bool = None

    @staticmethod
    def get_user_from_drone(email: str) -> Union['DroneUser', None]:  # pragma: no cover
        """Looks up drone user, installer, and dealer information for the given email
        address. Only returns installers or admins.
        :param email: An email address to look up in the bmapi_user table
        :return: DroneUser or None if no matching user is found
        """
        with connections['drone_db'].cursor() as cursor:
            cursor.execute("""
                SELECT us.id as drone_user_id, us.email, us.cognito_sub,
                    us.phone_number as id_phone_number, us.first_name, us.last_name,
                    us.access_type, us.latest_global_logout, inst.id as installer_id,
                    deal.id as dealer_id, deal.retired_date as dealer_retired_date,
                    inst.is_owner as is_company_owner
                FROM bmapi_user AS us
                LEFT JOIN bmapi_installer as inst ON inst.user_id = us.id
                LEFT JOIN bmapi_dealer as deal ON deal.id = inst.dealer_id
                WHERE us.email = %s AND (us.access_type = %s OR us.access_type = %s)
                LIMIT 1
            """, [email, constants.FIRSTECH_INSTALLER, constants.FIRSTECH_ADMIN])
            try:
                row = cursor.fetchall()[0]
            except IndexError:
                return None

            drone_user_info = DroneUser(*row)

        return drone_user_info


def get_or_create_user_with_drone_profile(
        token_email: Optional[str] = None,
        cognito_sub: Optional[str] = None,
        issued_at: Optional[int] = 0
) -> Union[User, None]:
    """Given the bearer token that was supplied, check to see if that user exists in
    Drone IoT. If it does, then create or refresh a DroneUserProfile for it. Also create
    or update a SaleorUser for this account and attach the DroneUserProfile to it. The
    drone profile information will only be updated if the bearer token is newer than the
    last update_date on the profile.

    :param token_email: The email address contained in the jwt token
    :param cognito_sub: The Cognito sub from the jwt token
    :param issued_at: Timestamp that the jwt token was issued at
    :return: The Saleor User object or None if a valid drone user doesn't exist."""

    saleor_user = None

    # Try to find a saleor user with the cognito subscriber id given from the token
    if cognito_sub:
        saleor_user = User.objects.filter(
            droneuserprofile__cognito_sub=cognito_sub
        ).first()

    try:
        if not saleor_user:
            # try to find a user from the token's email since we didn't find a matching
            # cognito subscriber id
            saleor_user = User.objects.get(email=token_email)

        drone_profile = saleor_user.droneuserprofile

    except (User.DoesNotExist, DroneUserProfile.DoesNotExist):
        # Either we don't have a drone profile, or we don't have a user at all. In
        # either case we will need to try to create a drone profile for the user.
        if drone_user_info := DroneUser.get_user_from_drone(token_email):
            user_info = {
                'is_staff': drone_user_info.access_type == constants.FIRSTECH_ADMIN,
                'first_name': drone_user_info.first_name,
                'last_name': drone_user_info.last_name,
            }
        else:
            return saleor_user

        if not saleor_user:
            saleor_user = User.objects.create_user(email=token_email, **user_info)

        DroneUserProfile.objects.create(
            user=saleor_user,
            drone_user_id=drone_user_info.user_id,
            cognito_sub=drone_user_info.cognito_sub,
            latest_global_logout=drone_user_info.latest_global_logout,
            installer_id=drone_user_info.installer_id,
            dealer_id=drone_user_info.dealer_id,
            dealer_retired_date=drone_user_info.dealer_retired_date,
            id_phone_number=drone_user_info.id_phone_number,
            is_company_owner=drone_user_info.is_company_owner,
        )
    else:
        # The saleor user and drone profile already exist. Refresh the user info from
        # drone if the auth token is newer than the last update timestamp. Or update the
        # profile if it's been more than 1 hour since the last update (needed for our
        # never expiring internal tokens). Or update if the user's email doesn't match
        # the email contained in the token.
        token_iat = timezone.datetime.fromtimestamp(
            issued_at,
            tz=timezone.utc
        )
        if (
                saleor_user.email != token_email
                or token_iat > drone_profile.update_date
                or timezone.now() > drone_profile.update_date + relativedelta(hours=1)
        ):
            drone_profile.refresh_drone_profile(token_email)
            saleor_user.refresh_from_db()

    return saleor_user
