from dataclasses import dataclass
from dateutil.relativedelta import relativedelta

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
    dealer_id = models.IntegerField(unique=True, null=True)
    dealer_retired_date = models.DateTimeField(blank=True, null=True)

    def refresh_drone_profile(self):
        """Gets the latest and greatest user information from the Drone API. Updates the
        saleor user and/or drone_user_profile if any changes are detected. Only saves if
        there are changes to keep database writes to a minimum."""

        drone_user_info = DroneUser.get_user_from_drone(self.user.email)

        field_mappings = [
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

    @staticmethod
    def get_user_from_drone(email: str) -> 'DroneUser':  # pragma: no cover
        """Looks up drone user, installer, and dealer information for the given email
        address.
        :param email: An email address to look up in the bmapi_user table
        :return: DroneUser or None if no matching user is found
        """
        with connections['drone_db'].cursor() as cursor:
            cursor.execute("""
                SELECT us.id as drone_user_id, us.email, us.cognito_sub,
                    us.phone_number as id_phone_number, us.first_name, us.last_name,
                    us.access_type, us.latest_global_logout, inst.id as installer_id,
                    deal.id as dealer_id, deal.retired_date as dealer_retired_date
                FROM bmapi_user AS us
                LEFT JOIN bmapi_installer as inst ON inst.user_id = us.id
                LEFT JOIN bmapi_dealer as deal ON deal.id = inst.dealer_id
                WHERE us.email = %s
                LIMIT 1
            """, [email])
            try:
                row = cursor.fetchall()[0]
            except IndexError:
                return None

            drone_user_info = DroneUser(*row)

        return drone_user_info


def get_or_create_user_with_drone_profile(jwt_payload: dict) -> User:
    """Given the bearer token that was supplied, check to see if that user exists in
    Drone IoT. If it does, then create or refresh a DroneUserProfile for it. Also create
    or update a SaleorUser for this account and attach the DroneUserProfile to it. The
    drone profile information will only be updated if the bearer token is newer than the
    last update_date on the profile.

    :param jwt_payload: A dict containing the jwt bearer token information
    :return: The Saleor User object"""

    if jwt_payload['iss'] == 'internal':
        email = jwt_payload['sub']
    else:
        email = jwt_payload['email']

    drone_user_info = None
    drone_user_checked = False

    # Get or create the Saleor User object
    try:
        saleor_user = User.objects.get(email=email)
    except User.DoesNotExist:
        if drone_user_info := DroneUser.get_user_from_drone(email):
            user_info = {
                'is_staff': drone_user_info.access_type == constants.FIRSTECH_ADMIN,
                'first_name': drone_user_info.first_name,
                'last_name': drone_user_info.last_name,
            }
        else:
            user_info = {}
            drone_user_checked = True

        saleor_user = User.objects.create_user(email=email, **user_info)

    # Get or create the DroneUserProfile for the Saleor User
    try:
        drone_profile = DroneUserProfile.objects.get(user=saleor_user)
    except DroneUserProfile.DoesNotExist:
        if not drone_user_info and not drone_user_checked:
            drone_user_info = DroneUser.get_user_from_drone(email)
        if drone_user_info:
            DroneUserProfile.objects.create(
                user=saleor_user,
                drone_user_id=drone_user_info.user_id,
                cognito_sub=drone_user_info.cognito_sub,
                latest_global_logout=drone_user_info.latest_global_logout,
                installer_id=drone_user_info.installer_id,
                dealer_id=drone_user_info.dealer_id,
                dealer_retired_date=drone_user_info.dealer_retired_date,
                id_phone_number=drone_user_info.id_phone_number,
            )
    else:
        # The saleor user and drone profile already exist. Refresh the user info from
        # drone if the auth token is newer than the last update timestamp. Or update the
        # profile if it's been more than 1 hour since the last update (needed for our
        # never expiring internal tokens)
        token_iat = timezone.datetime.fromtimestamp(
            jwt_payload.get('iat', 0),
            tz=timezone.utc
        )
        if token_iat > drone_profile.update_date or \
                timezone.now() > drone_profile.update_date + relativedelta(hours=1):
            drone_profile.refresh_drone_profile()
            saleor_user.refresh_from_db()

    return saleor_user
