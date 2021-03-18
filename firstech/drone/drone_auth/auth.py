

from . import (
    AuthenticationError,
    InvalidUserError,
    MissingCredentialsError,

    authenticate_by_auth_header,
)

HTTP_HEADER_ENCODING = 'iso-8859-1'


def get_authorization_header(request):
    """
    Return request's 'Authorization:' header, as a bytestring.

    Hide some test client ickyness where the header can be unicode.
    """
    auth = request.META.get('HTTP_AUTHORIZATION', b'')
    if isinstance(auth, str):
        # Work around django test client oddness
        auth = auth.encode(HTTP_HEADER_ENCODING)
    return auth


class JSONWebTokenAuthentication():
    """Token based authentication using the JSON Web Token standard."""

    def authenticate(self, request):
        """Entrypoint for Django Rest Framework"""
        try:
            user = authenticate_by_auth_header(
                get_authorization_header(request).decode('latin-1')
            )
            return user
        except MissingCredentialsError:
            return None
        except InvalidUserError as exc:
            # TODO: In drone we raise slight variations of a 403 that django-rest
            # framework provides. Do we want to do that or just return None?
            return None
        except AuthenticationError as exc:
            if exc.details:
                return None
            return None
