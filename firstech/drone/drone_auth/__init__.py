from __future__ import annotations

from typing import *

from django.conf import settings
from django.utils import timezone

from saleor.account.models import User
from firstech.drone.models import get_or_create_user_with_drone_profile

from . import jwt_validators


class AuthenticationError(Exception):
    details = None

    def __init__(self, details=None):
        self.details = details


class MissingCredentialsError(AuthenticationError):
    pass


class InvalidUserError(AuthenticationError):
    pass


JWT_VALIDATORS = []

if settings.DRONE_COGNITO_POOL_ID:  # pragma: no cover
    cognito_validator = jwt_validators.CognitoIdTokenValidator(
        settings.DRONE_AWS_DEFAULT_REGION,
        settings.DRONE_COGNITO_POOL_ID,
    )
    JWT_VALIDATORS.append(cognito_validator)

if settings.DRONE_API_SECRET_KEY:
    internal_validator = jwt_validators.InternalTokenValidator(
        settings.DRONE_API_SECRET_KEY
    )
    JWT_VALIDATORS.append(internal_validator)


JWT_VALIDATOR = jwt_validators.CompositeTokenValidator(JWT_VALIDATORS)


def get_jwt_token(authorization_header: Optional[str]) -> str:
    """
    :raises: MissingCredentialsError
    """
    if not authorization_header:
        raise MissingCredentialsError()

    auth = authorization_header.split()
    if not auth:
        raise MissingCredentialsError()
    elif auth[0].lower() != 'bearer':
        raise AuthenticationError(
            'Invalid Authorization header. Must be a bearer token.'
        )
    elif len(auth) == 1:
        raise AuthenticationError(
            'Invalid Authorization header. No credentials provided.'
        )
    elif len(auth) > 2:
        raise AuthenticationError(
            'Invalid Authorization header. Credentials string '
            'should not contain spaces.'
        )

    return auth[1]


def authenticate_by_token(jwt_token: str) -> User:
    """
    :raises: AuthenticationError
    :raises: InvalidUserError
    :return: User object
    """
    try:
        jwt_payload = JWT_VALIDATOR.validate(jwt_token)
    except jwt_validators.TokenError:
        raise AuthenticationError()

    user = get_or_create_user_with_drone_profile(jwt_payload)

    if hasattr(user, 'droneuserprofile'):
        # Disallow installers associated with retired dealers
        if (
            user.droneuserprofile.installer_id and
            user.droneuserprofile.dealer_id and
            user.droneuserprofile.dealer_retired_date
        ):
            raise InvalidUserError()

        # Disallow tokens that were issued prior to the user's most recent global logout
        if user.droneuserprofile.latest_global_logout:
            jwt_iat = jwt_payload.get('iat', 0)
            issued_at = timezone.datetime.fromtimestamp(jwt_iat, tz=timezone.utc)
            if issued_at < user.droneuserprofile.latest_global_logout:
                raise AuthenticationError(
                    'Your login credentials need to be refreshed due to a recent change'
                    ' you have made. Please login again to resume application access.'
                )

    return user


def authenticate_by_auth_header(authorization_header: Optional[str]) -> User:
    """
    :param authorization_header: The value of the authorization header, or None if it's missing
    :raises: AuthenticationError
    :raises: InvalidUserError
    :raises: MissingCredentialsError
    :return: A tuple of a User object and the JWT token
    """
    jwt_token = get_jwt_token(authorization_header)
    return authenticate_by_token(jwt_token)
