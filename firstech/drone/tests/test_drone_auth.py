from unittest import mock

import jwt
import pytest
from Cryptodome.PublicKey import RSA
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from freezegun import freeze_time
from jwt.utils import to_base64url_uint

from firstech.drone.drone_auth import (
    JWT_VALIDATORS,
    AuthenticationError,
    InvalidUserError,
    MissingCredentialsError,
    authenticate_by_auth_header,
    authenticate_by_token,
    get_jwt_token,
)
from firstech.drone.drone_auth.jwt_validators import (
    CognitoAccessTokenValidator,
    CognitoIdTokenValidator,
    CompositeTokenValidator,
)
from saleor import settings

######### The "cluster" below is taken from the Drone bmapi unit tests #################

# Okay, so this is a cluster because we basically have to spoof the entire JWT/JWK setup that Cognito uses locally
# in order for the tests to work. To do this, we first generate an RSA private/public key. We then setup the list of
# validators by hand (these are otherwise instantiated when including the module for the first time, so we can't easily
# mock them). We then provide a local utility function for creating the JWT tokens that will be cryptographically valid
# given our generated certificate.
JWT_ISSUER = "local_tests"
JWT_KID = "local_example"
_key = RSA.generate(2048)
JWT_PRIVATE_KEY = _key.export_key().decode("utf-8")
JWT_PUBLIC_KEY_N = _key.publickey().n
JWT_VALIDATORS_OVERRIDE = [x for x in JWT_VALIDATORS]
JWT_VALIDATORS_OVERRIDE.append(CognitoIdTokenValidator(None, None))
JWT_VALIDATORS_OVERRIDE.append(CognitoAccessTokenValidator(None, None, None))


def _create_jwt_token(data: dict, generate_default_properties=True, minutes_valid=10):
    """Creates a JWT token using the default RSA keys generated above"""
    if generate_default_properties:
        now = timezone.datetime.now(tz=timezone.utc)
        data["iat"] = now
        data["exp"] = now + timezone.timedelta(minutes=minutes_valid)
        data["iss"] = JWT_ISSUER

    return jwt.encode(
        data,
        JWT_PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": JWT_KID},
    )


########################################################################################


@mock.patch(
    "firstech.drone.drone_auth.jwt_validators.CognitoIdTokenValidator._cognito_pool_url",
    JWT_ISSUER,
)
@mock.patch(
    "firstech.drone.drone_auth.jwt_validators.CognitoIdTokenValidator._json_web_keys",
    {
        JWT_KID: f"""
                {{
                    "alg":"RS256",
                    "e":"AQAB",
                    "kid":"{JWT_KID}",
                    "kty":"RSA",
                    "n":"{to_base64url_uint(JWT_PUBLIC_KEY_N).decode('ascii')}",
                    "use":"sig"
                }}
                """
    },
)
@mock.patch(
    "firstech.drone.drone_auth.JWT_VALIDATOR",
    CompositeTokenValidator(JWT_VALIDATORS_OVERRIDE),
)
class TestCognitoAuthentication:
    def test_cognito_token_auth(self, complete_user):
        # Test that cognito tokens are authenticated using our drone auth backend
        token = _create_jwt_token(
            {
                "sub": complete_user.droneuserprofile.cognito_sub,
                "cognito:username": complete_user.droneuserprofile.cognito_sub,
                "email": complete_user.email,
                "phone_number": complete_user.droneuserprofile.id_phone_number,
            }
        )

        user = authenticate_by_token(token)
        assert user == complete_user

    def test_migrate_drone_user(self, mocked_get_user_from_drone):
        # Test that a drone_profile and saleor user is created for cognito tokens that
        # already exist inside the drone app.

        with mock.patch("firstech.drone.models.DroneUser.get_user_from_drone") as mck:
            mck.side_effect = mocked_get_user_from_drone

            drone_sub = "new_guy_sub"
            drone_email = "droney@example.com"
            drone_phone = "+15555555555"

            token = _create_jwt_token(
                {
                    "sub": drone_sub,
                    "cognito:username": drone_sub,
                    "email": drone_email,
                    "phone_number": drone_phone,
                }
            )

            user = authenticate_by_token(token)
            assert user.first_name == "droney"
            assert user.email == drone_email
            assert user.droneuserprofile.id_phone_number == drone_phone

    def test_refresh_drone_user(self, complete_user, mocked_get_user_from_drone):
        # Tests that a drone profile is updated when a new token is used
        with mock.patch("firstech.drone.models.DroneUser.get_user_from_drone") as mck:
            mck.side_effect = mocked_get_user_from_drone

            # Ensure our token is newer than the last update date of the user so
            # we ensure a refresh
            with freeze_time(timezone.now() + relativedelta(minutes=1)):
                token = _create_jwt_token(
                    {
                        "sub": complete_user.droneuserprofile.cognito_sub,
                        "cognito:username": complete_user.droneuserprofile.cognito_sub,
                        "email": complete_user.email,
                        "phone_number": complete_user.droneuserprofile.id_phone_number,
                    }
                )

                assert complete_user.first_name == "some"
                assert complete_user.last_name == "guy"
                assert complete_user.droneuserprofile.drone_user_id == 12345

                user = authenticate_by_token(token)

                # The "complete_user" has been updated with the info that comes from
                # the mocked get_user_from_drone function
                assert user.first_name == "droney"
                assert user.last_name == "baloney"
                assert user.droneuserprofile.drone_user_id == 1234567

    def test_lookup_drone_info_for_existing_user(
        self, saleor_user, drone_user, mocked_get_user_from_drone
    ):
        # Test that we try to get drone info for existing saleor users

        assert hasattr(saleor_user, "droneuserprofile") is False

        with mock.patch("firstech.drone.models.DroneUser.get_user_from_drone") as mck:
            mck.side_effect = mocked_get_user_from_drone

            token = _create_jwt_token(
                {
                    "sub": drone_user.cognito_sub,
                    "cognito:username": drone_user.cognito_sub,
                    "email": drone_user.email,
                    "phone_number": drone_user.id_phone_number,
                }
            )
            user = authenticate_by_token(token)
            saleor_user.refresh_from_db()

            assert user == saleor_user
            assert hasattr(saleor_user, "droneuserprofile")

    def test_no_refresh_old_token(self, complete_user, mocked_get_user_from_drone):
        # Test that using an older token (but not older than 1 hour) does not trigger
        # a refresh from the drone database.
        with mock.patch("firstech.drone.models.DroneUser.get_user_from_drone") as mck:
            mck.side_effect = mocked_get_user_from_drone

            # Force the token to be 10 minutes old
            with freeze_time(timezone.now() - relativedelta(minutes=10)):
                token = _create_jwt_token(
                    {
                        "sub": complete_user.droneuserprofile.cognito_sub,
                        "cognito:username": complete_user.droneuserprofile.cognito_sub,
                        "email": complete_user.email,
                        "phone_number": complete_user.droneuserprofile.id_phone_number,
                    }
                )

                assert complete_user.first_name == "some"
                assert complete_user.last_name == "guy"
                assert complete_user.droneuserprofile.drone_user_id == 12345

                user = authenticate_by_token(token)

                # The "complete_user" has NOT been updated
                assert user.first_name == "some"
                assert user.last_name == "guy"
                assert user.droneuserprofile.drone_user_id == 12345

    def test_expired_token(self, complete_user):
        # Test that old tokens are not authenticated
        # Force the token to be just over an hour old
        with freeze_time(timezone.now() - relativedelta(hours=1, minutes=1)):
            token = _create_jwt_token(
                {
                    "sub": complete_user.droneuserprofile.cognito_sub,
                    "cognito:username": complete_user.droneuserprofile.cognito_sub,
                    "email": complete_user.email,
                    "phone_number": complete_user.droneuserprofile.id_phone_number,
                }
            )

        with pytest.raises(AuthenticationError):
            authenticate_by_token(token)

    def test_no_such_user(self, mocked_get_user_from_drone):
        # Test that users that login with cognito, but don't have a drone user, are not
        # authenticated
        dead_sub = "example_sub_2"
        dead_email = "dead@example.com"
        dead_phone = "+15555555555"

        with mock.patch("firstech.drone.models.DroneUser.get_user_from_drone") as mck:
            mck.side_effect = mocked_get_user_from_drone

            token = _create_jwt_token(
                {
                    "sub": dead_sub,
                    "cognito:username": dead_sub,
                    "email": dead_email,
                    "phone_number": dead_phone,
                }
            )

            user = authenticate_by_token(token)

            assert user is None

    def test_retired_dealer_installer(self, complete_installer_user):
        """Installers for retired dealers must not be allowed access"""

        complete_installer_user.droneuserprofile.dealer_retired_date = timezone.now()
        complete_installer_user.droneuserprofile.save()

        token = _create_jwt_token(
            {
                "sub": complete_installer_user.droneuserprofile.cognito_sub,
                "cognito:username": complete_installer_user.droneuserprofile.cognito_sub,
                "email": complete_installer_user.email,
                "phone_number": complete_installer_user.droneuserprofile.id_phone_number,
            }
        )
        with pytest.raises(InvalidUserError):
            authenticate_by_token(token)

    def test_invalidated_token_due_to_global_logout(self, complete_user):
        """Users who have globally logged out must not be able to validate old tokens"""
        now = timezone.now()
        # Create a token that's 5 minutes old
        with freeze_time(now - timezone.timedelta(minutes=5)):
            token = _create_jwt_token(
                {
                    "sub": complete_user.droneuserprofile.cognito_sub,
                    "cognito:username": complete_user.droneuserprofile.cognito_sub,
                    "email": complete_user.email,
                    "phone_number": complete_user.droneuserprofile.id_phone_number,
                }
            )
        # Mark the user as globally logged out
        complete_user.droneuserprofile.latest_global_logout = timezone.now()
        complete_user.droneuserprofile.save()
        # Attempt to verify the old token
        with pytest.raises(AuthenticationError):
            authenticate_by_token(token)


class GetJWTTokenTestCase:
    """Tests for `get_jwt_token()` utility method that accepts Authorization header and
    return the bearer token string. These are a straight duplication of the tests inside
     the drone app.
    """

    def test_none_authorization_header(self):
        """`None` authorization headers must throw appropriate errors"""
        with pytest.raises(MissingCredentialsError):
            get_jwt_token(None)

    def test_empty_authorization_header(self):
        """Empty authorization headers must fail"""
        with pytest.raises(MissingCredentialsError):
            get_jwt_token("")

    def test_whitespace_authorization_header(self):
        """Whitespace-only authorization headers must fail"""
        with pytest.raises(MissingCredentialsError):
            get_jwt_token("   ")

    def test_no_bearer_keyword(self):
        """Missing bearer keyword headers must fail"""
        with pytest.raises(AuthenticationError):
            get_jwt_token("Bad Token")

    def test_only_bearer_keyword(self):
        """Only bearer keyword must fail"""
        with pytest.raises(AuthenticationError):
            get_jwt_token("Bearer ")

    def test_too_many_spaces(self):
        """Headers with too many spaces must fail"""
        with pytest.raises(AuthenticationError):
            get_jwt_token("Bearer token anotherToken")

    def test_get_token(self):
        """Unpadded token string must be returned"""
        token = "token"
        assert get_jwt_token(f"Bearer {token}") == token


class TestInternalTokens:
    @staticmethod
    def generate_internal_token(
        email: str, validity_mins: int, key=settings.DRONE_API_SECRET_KEY
    ):
        """These token are not created by the saleor app or the firstech add on. These
        are only created by the drone bmapp. This function exists inside this test so
        that we can be sure that we can authorize them."""
        now = timezone.now()

        payload = {
            "sub": email,
            "iss": "internal",
            "aud": "internal",
            "token_use": "id",
            "iat": now,
            "exp": now + timezone.timedelta(minutes=validity_mins),
        }
        id_token = jwt.encode(payload, key, algorithm="HS256")

        return id_token

    @staticmethod
    def format_token(id_token):
        return f"bearer {id_token}"

    def test_internal_token_valid(self, complete_user):
        token = self.format_token(
            TestInternalTokens.generate_internal_token(
                email=complete_user.email,
                validity_mins=10,
            )
        )

        user = authenticate_by_auth_header(token)
        assert user is not None

    def test_no_token(self):
        with pytest.raises(AuthenticationError):
            authenticate_by_auth_header(None)

    def test_internal_token_incorrect_signature(self):
        token = self.format_token(
            TestInternalTokens.generate_internal_token(
                email="testuser@example.com",
                validity_mins=10,
                key="incorrectkey",
            )
        )
        with pytest.raises(AuthenticationError):
            authenticate_by_auth_header(token)

    def test_internal_token_missing_sub(self):
        now = timezone.datetime.now()

        payload = {
            "iss": "internal",
            "aud": "internal",
            "token_use": "id",
            "iat": now,
            "exp": now + timezone.timedelta(minutes=10),
        }
        id_token = jwt.encode(payload, settings.DRONE_API_SECRET_KEY, algorithm="HS256")
        token = self.format_token(id_token)

        with pytest.raises(AuthenticationError):
            authenticate_by_auth_header(token)

    def test_internal_token_expired(self):
        token = self.format_token(
            TestInternalTokens.generate_internal_token(
                email="testuser@example.com",
                validity_mins=-10,
            )
        )
        with pytest.raises(AuthenticationError):
            authenticate_by_auth_header(token)

    def test_internal_malformed_bearer_token(self):
        token = self.format_token("XXX")
        with pytest.raises(AuthenticationError):
            authenticate_by_auth_header(token)

    def test_internal_malformed_token(self):
        token = "XXX"
        with pytest.raises(AuthenticationError):
            authenticate_by_auth_header(token)
