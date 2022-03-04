import pytest

from firstech.drone.models import DroneUser, DroneUserProfile
from firstech.drone.tests.test_drone_auth import _create_jwt_token
from saleor.account.models import User

COGNITO_SUB = "random_cognito_subscriber_jargon"


@pytest.fixture()
def cognito_token():
    data = {
        "sub": COGNITO_SUB,
        "cognito:username": COGNITO_SUB,
        "email": "droneinator@example.com",
        "phone_number": "+15555555555",
    }
    return _create_jwt_token(data)


@pytest.fixture()
def drone_user():
    return DroneUser(
        user_id=12345,
        email="user@example.com",
        first_name="some",
        last_name="guy",
        cognito_sub=COGNITO_SUB,
        access_type="ordinary_user",
        id_phone_number="+15555555555",
    )


@pytest.fixture()
def drone_installer_user():
    return DroneUser(
        user_id=12345,
        email="installer@example.com",
        first_name="some",
        last_name="guy",
        cognito_sub=COGNITO_SUB,
        access_type="ordinary_user",
        id_phone_number="+15555555555",
        installer_id=12345,
        dealer_id=6789,
    )


@pytest.fixture()
def saleor_user():
    return User.objects.create_user(
        email="user@example.com",
        first_name="Saley",
        last_name="McBaley",
    )


@pytest.fixture()
def complete_user(drone_user):
    # A Saleor user with attached drone profile
    user = User.objects.create_user(
        email=drone_user.email,
        first_name=drone_user.first_name,
        last_name=drone_user.last_name,
    )

    DroneUserProfile.objects.create(
        user=user,
        drone_user_id=drone_user.user_id,
        cognito_sub=drone_user.cognito_sub,
        id_phone_number=drone_user.id_phone_number,
        latest_global_logout=drone_user.latest_global_logout,
        installer_id=drone_user.installer_id,
        dealer_id=drone_user.dealer_id,
        dealer_retired_date=drone_user.dealer_retired_date,
    )

    return user


@pytest.fixture()
def complete_installer_user(drone_installer_user):
    # A Saleor user with attached drone profile
    user = User.objects.create_user(
        email=drone_installer_user.email,
        first_name=drone_installer_user.first_name,
        last_name=drone_installer_user.last_name,
    )

    DroneUserProfile.objects.create(
        user=user,
        drone_user_id=drone_installer_user.user_id,
        cognito_sub=drone_installer_user.cognito_sub,
        id_phone_number=drone_installer_user.id_phone_number,
        latest_global_logout=drone_installer_user.latest_global_logout,
        installer_id=drone_installer_user.installer_id,
        dealer_id=drone_installer_user.dealer_id,
        dealer_retired_date=drone_installer_user.dealer_retired_date,
    )

    return user


@pytest.fixture(name="mocked_get_user_from_drone")
def mocked_get_user_from_drone(mocker):
    def _mock_func(email):
        if email == "dead@example.com":
            return None
        elif email == "ordinary@example.com":
            return DroneUser(
                user_id=1234567,
                email=email,
                cognito_sub="new_guy_sub",
                id_phone_number="+15555555555",
                first_name="droney",
                last_name="baloney",
                access_type="ordinary_user",
            )
        else:
            return DroneUser(
                user_id=1234567,
                email=email,
                cognito_sub="new_guy_sub",
                id_phone_number="+15555555555",
                first_name="droney",
                last_name="baloney",
            )

    return _mock_func
