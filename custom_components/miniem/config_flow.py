"""Set-up: paste the Firebase service account key that may send to the launcher."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig

from .const import CONF_SERVICE_ACCOUNT, DOMAIN
from .fcm import FcmClient, ServiceAccountError, parse_service_account

SCHEMA = vol.Schema(
    {vol.Required(CONF_SERVICE_ACCOUNT): TextSelector(TextSelectorConfig(multiline=True))}
)


class MiniemConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                account = parse_service_account(user_input[CONF_SERVICE_ACCOUNT])
                # Prove the key works before storing it: a bad key would otherwise only
                # show up as pushes that never arrive.
                await FcmClient(async_get_clientsession(self.hass), account).access_token()
            except ServiceAccountError as err:
                errors["base"] = "token_refused" if str(err).startswith("token_refused") else str(err)
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"Miniem ({account['project_id']})",
                    data={CONF_SERVICE_ACCOUNT: account},
                )
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)
