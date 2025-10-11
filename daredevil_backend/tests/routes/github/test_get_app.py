import pytest
from jwt import InvalidIssuerError

from ....configs import GithubAppLib


def test_no_client_id_jwt_fail():
    client_id = "1234"
    gh_app_lib = GithubAppLib()

    jwt = gh_app_lib.create_jwt(client_id=client_id)
    assert isinstance(jwt, str)
