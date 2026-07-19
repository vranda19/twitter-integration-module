"""
tests/unit/test_token_service.py

Unit tests for TwitterTokenService — the automatic refresh logic
that guarantees "no manual login" (Part 5).

Mocks: TwitterAccountRepository (no real DB), and httpx via monkeypatch
(no real network call to Twitter's token endpoint).
"""


import httpx
import pytest

from app.core.security import decrypt_token
from app.exceptions.twitter_exceptions import TokenRefreshError, TwitterAccountNotFoundError
from app.services.twitter_token_service import TwitterTokenService
from tests.mocks.twitter_api_mock import mock_token_exchange_response


@pytest.mark.asyncio
async def test_returns_existing_token_when_not_expiring_soon(fake_account, mock_account_repository):
    mock_account_repository.get_by_id.return_value = fake_account
    service = TwitterTokenService(mock_account_repository)

    token = await service.get_valid_access_token(fake_account.id, fake_account.user_id)

    assert token == "PLAINTEXT_ACCESS_TOKEN"
    mock_account_repository.update_tokens.assert_not_called()


@pytest.mark.asyncio
async def test_raises_not_found_when_account_missing(mock_account_repository):
    mock_account_repository.get_by_id.return_value = None
    service = TwitterTokenService(mock_account_repository)

    with pytest.raises(TwitterAccountNotFoundError):
        await service.get_valid_access_token("missing-id", "u-1234")


@pytest.mark.asyncio
async def test_raises_refresh_error_when_no_refresh_token(fake_expired_account, mock_account_repository):
    from dataclasses import replace

    account_without_refresh = replace(fake_expired_account, refresh_token=None)
    mock_account_repository.get_by_id.return_value = account_without_refresh
    service = TwitterTokenService(mock_account_repository)

    with pytest.raises(TokenRefreshError):
        await service.get_valid_access_token(account_without_refresh.id, account_without_refresh.user_id)


@pytest.mark.asyncio
async def test_refreshes_expired_token_and_persists_new_tokens(
    fake_expired_account, mock_account_repository, monkeypatch
):
    mock_account_repository.get_by_id.return_value = fake_expired_account
    mock_account_repository.update_tokens.return_value = fake_expired_account

    async def fake_post(self, url, data=None, auth=None, headers=None):  # noqa: ANN001
        return httpx.Response(200, json=mock_token_exchange_response(), request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    service = TwitterTokenService(mock_account_repository)
    token = await service.get_valid_access_token(fake_expired_account.id, fake_expired_account.user_id)

    assert token == "MOCK_ACCESS_TOKEN_abc123"
    mock_account_repository.update_tokens.assert_called_once()
    call_kwargs = mock_account_repository.update_tokens.call_args.kwargs
    assert decrypt_token(call_kwargs["encrypted_access_token"]) == "MOCK_ACCESS_TOKEN_abc123"


@pytest.mark.asyncio
async def test_refresh_failure_raises_token_refresh_error(fake_expired_account, mock_account_repository, monkeypatch):
    mock_account_repository.get_by_id.return_value = fake_expired_account

    async def fake_post(self, url, data=None, auth=None, headers=None):  # noqa: ANN001
        return httpx.Response(400, json={"error": "invalid_grant"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    service = TwitterTokenService(mock_account_repository)

    with pytest.raises(TokenRefreshError):
        await service.get_valid_access_token(fake_expired_account.id, fake_expired_account.user_id)
