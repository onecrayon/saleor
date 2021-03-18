import json

import requests

from django.utils.functional import cached_property
import jwt


class TokenError(Exception):
    pass


class CompositeTokenValidator:
    def __init__(self, validators: list):
        self.validators = validators

    def validate(self, token):
        for validator in self.validators:
            try:
                payload = validator.validate(token)
                return payload
            except TokenError:
                continue

        raise TokenError('Can\'t match token with any validator')


class InternalTokenValidator:
    def __init__(self, private_key: str):
        self.private_key = private_key

    def validate(self, token):
        try:
            jwt_data = jwt.decode(
                token,
                self.private_key,
                audience='internal',
                issuer='internal',
                algorithms=['HS256'],
            )
            if 'sub' not in jwt_data:
                raise TokenError('Invalid token, must contain sub')

            return jwt_data
        except (jwt.InvalidTokenError, jwt.ExpiredSignature, jwt.DecodeError) as exc:
            raise TokenError(str(exc)) from exc


class CognitoIdTokenValidator:
    """
    Id tokens using for api access

    """

    def __init__(self, aws_region, aws_user_pool):
        self.aws_region = aws_region
        self.aws_user_pool = aws_user_pool

    @cached_property
    def _cognito_pool_url(self):  # pragma: no cover
        return 'https://cognito-idp.%s.amazonaws.com/%s' % (
            self.aws_region, self.aws_user_pool)

    @cached_property
    def _json_web_keys(self):  # pragma: no cover
        # TODO: update this to download and cache the token only as needed; maybe using redis? Currently falling back
        #  to a statically uploaded file in S3 in case Amazon runs into any more errors serving this file
        try:
            response = requests.get(
                self._cognito_pool_url + '/.well-known/jwks.json',
                timeout=1,
            )
            response.raise_for_status()
        except:
            response = requests.get(
                f'https://bmapp-prod-static.s3.amazonaws.com/{ENV_NAME}-jwks.json',
                timeout=10,
            )
            response.raise_for_status()

        json_data = response.json()
        return {item['kid']: json.dumps(item) for item in json_data['keys']}

    def _get_public_key(self, token):
        try:
            headers = jwt.get_unverified_header(token)
        except jwt.DecodeError as exc:
            raise TokenError(str(exc))

        if 'kid' not in headers:
            return None

        jwk_data = self._json_web_keys.get(headers['kid'])
        if not jwk_data:
            return None

        return jwt.algorithms.RSAAlgorithm.from_jwk(jwk_data)

    def parse_token(self, token):
        public_key = self._get_public_key(token)
        if not public_key:
            raise TokenError('No key found for this token')

        try:
            jwt_data = jwt.decode(
                token,
                public_key,
                issuer=self._cognito_pool_url,
                options={'verify_aud': False},
                algorithms=['RS256'],
            )
            return jwt_data
        except (jwt.InvalidTokenError, jwt.ExpiredSignature, jwt.DecodeError) as exc:
            raise TokenError(str(exc)) from exc

    def validate(self, token):
        jwt_data = self.parse_token(token)
        required_attrs = frozenset(['sub', 'iss', 'cognito:username', 'email', 'phone_number', 'iat'])
        if required_attrs - frozenset(jwt_data.keys()):
            raise TokenError('Invalid token: not all fields present')

        return jwt_data


class CognitoAccessTokenValidator(CognitoIdTokenValidator):
    """
    Access tokens using for oauth clients
    """
    def __init__(self, aws_region, aws_user_pool, client_id):
        self.client_id = client_id
        super().__init__(aws_region, aws_user_pool)

    def validate(self, token):
        jwt_data = self.parse_token(token)
        required_attrs = frozenset(['sub', 'iss', 'username'])
        if required_attrs - frozenset(jwt_data.keys()):
            raise TokenError('Invalid token: not all fields present')

        if jwt_data['client_id'] != self.client_id:
            raise TokenError('Invalid token: client_id mismatch')

        return jwt_data
