import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from app.webapp import WebAppAuthError, verify_init_data


def signed_init_data(bot_token: str, user: dict) -> str:
    values = {
        "auth_date": "1710000000",
        "query_id": "test",
        "user": json.dumps(user, separators=(",", ":")),
    }
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode(),
        hashlib.sha256,
    ).digest()
    values["hash"] = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(values)


def test_verify_init_data_accepts_valid_signature() -> None:
    bot_token = "123:TEST"
    data = signed_init_data(bot_token, {"id": 42, "first_name": "Ali"})

    assert verify_init_data(data, bot_token)["id"] == 42


def test_verify_init_data_rejects_tampering() -> None:
    bot_token = "123:TEST"
    data = signed_init_data(bot_token, {"id": 42, "first_name": "Ali"})
    tampered = data.replace("Ali", "Vali")

    with pytest.raises(WebAppAuthError):
        verify_init_data(tampered, bot_token)

