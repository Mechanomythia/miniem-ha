"""Firebase Cloud Messaging (HTTP v1), straight from Home Assistant.

No Firebase SDK: a service-account JWT is exchanged for an access token, which is
cached until shortly before it expires. PyJWT and cryptography both ship with Home
Assistant, so the integration has no requirements of its own.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import jwt
from aiohttp import ClientError, ClientSession, ClientTimeout

_LOGGER = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
TIMEOUT = ClientTimeout(total=15)
SEND_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"


class ServiceAccountError(ValueError):
    """The pasted service account is not one we can use."""


class TokenUnregistered(Exception):
    """FCM says this phone's token is no longer valid."""


def parse_service_account(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Validate a service account JSON key and return it as a dict."""
    try:
        account = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError) as err:
        raise ServiceAccountError("not_json") from err
    for field in ("project_id", "client_email", "private_key", "token_uri"):
        if not account.get(field):
            raise ServiceAccountError("missing_fields")
    if account.get("type") != "service_account":
        raise ServiceAccountError("not_service_account")
    return account


class FcmClient:
    """Sends data messages to phones."""

    def __init__(self, session: ClientSession, account: dict[str, Any]) -> None:
        self._session = session
        self._account = account
        self._token: str | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()

    @property
    def project_id(self) -> str:
        return self._account["project_id"]

    async def access_token(self) -> str:
        """An OAuth access token for FCM, fetched again shortly before it expires."""
        async with self._lock:
            if self._token and time.time() < self._expires - 60:
                return self._token
            now = int(time.time())
            assertion = jwt.encode(
                {
                    "iss": self._account["client_email"],
                    "scope": SCOPE,
                    "aud": TOKEN_URL,
                    "iat": now,
                    "exp": now + 3600,
                },
                self._account["private_key"],
                algorithm="RS256",
                headers={"kid": self._account.get("private_key_id")} if self._account.get("private_key_id") else None,
            )
            async with self._session.post(
                TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                timeout=TIMEOUT,
            ) as response:
                body = await response.json(content_type=None)
                if response.status != 200 or "access_token" not in body:
                    raise ServiceAccountError(f"token_refused: {body}")
            self._token = body["access_token"]
            self._expires = now + int(body.get("expires_in", 3600))
            return self._token

    async def send(self, push_token: str, data: dict[str, str]) -> None:
        """Send one high-priority data message. Raises TokenUnregistered for dead tokens."""
        access = await self.access_token()
        message = {
            "message": {
                "token": push_token,
                "data": {key: str(value) for key, value in data.items()},
                "android": {"priority": "high", "ttl": "600s"},
            }
        }
        try:
            async with self._session.post(
                SEND_URL.format(project=self.project_id),
                json=message,
                headers={"Authorization": f"Bearer {access}"},
                timeout=TIMEOUT,
            ) as response:
                if response.status == 200:
                    return
                body = await response.text()
                if response.status == 404 or "UNREGISTERED" in body:
                    raise TokenUnregistered(body)
                _LOGGER.warning("FCM refused a message (%s): %s", response.status, body)
        except ClientError as err:
            _LOGGER.warning("Could not reach FCM: %s", err)
