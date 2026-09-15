from __future__ import annotations

import pytest

from aide.api.demo_http import (
    HttpDemoMisconfiguredError,
    env_flag_enabled,
    parse_demo_token,
    resolve_http_demo,
)


def test_http_demo_flag_defaults_disabled() -> None:
    assert env_flag_enabled(None) is False
    assert env_flag_enabled("") is False
    assert env_flag_enabled("0") is False
    assert env_flag_enabled("false") is False
    assert env_flag_enabled("1") is True
    assert env_flag_enabled("true") is True


def test_parse_demo_token_rejects_blank_values() -> None:
    assert parse_demo_token(None) is None
    assert parse_demo_token("") is None
    assert parse_demo_token("   ") is None
    assert parse_demo_token("gate") == "gate"


def test_resolve_http_demo_disabled_does_not_need_token() -> None:
    assert resolve_http_demo(http_enabled=False, token=None) is None
    assert resolve_http_demo(http_enabled=False, token="gate") is None


def test_resolve_http_demo_enabled_fails_closed_without_token() -> None:
    with pytest.raises(HttpDemoMisconfiguredError, match="AIDE_SYNTHETIC_DEMO_TOKEN"):
        resolve_http_demo(http_enabled=True, token=None)
    with pytest.raises(HttpDemoMisconfiguredError, match="AIDE_SYNTHETIC_DEMO_TOKEN"):
        resolve_http_demo(http_enabled=True, token="")
    with pytest.raises(HttpDemoMisconfiguredError, match="AIDE_SYNTHETIC_DEMO_TOKEN"):
        resolve_http_demo(http_enabled=True, token="  ")


def test_resolve_http_demo_enabled_returns_token() -> None:
    assert resolve_http_demo(http_enabled=True, token="gate") == "gate"
    assert resolve_http_demo(http_enabled=True, token="  gate ") == "gate"
