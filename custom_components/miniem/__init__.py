"""Miniem: server-driven cards on the launcher's Home Assistant panel."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_CARD,
    ATTR_CARD_ID,
    ATTR_DEVICE_ID,
    ATTR_FOCUS,
    ATTR_NOTIFICATION_BODY,
    ATTR_NOTIFICATION_TITLE,
    ATTR_PRIORITY,
    ATTR_TTL,
    CONF_SERVICE_ACCOUNT,
    DOMAIN,
    SERVICE_CLEAR_CARD,
    SERVICE_SHOW_CARD,
)
from .fcm import FcmClient, ServiceAccountError, parse_service_account
from .http import ActionView, CardsView, RegisterView
from .hub import MiniemHub

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _card(value: Any) -> dict[str, Any]:
    """A card needs an id and something to show; the phone validates the rest."""
    if not isinstance(value, dict):
        raise vol.Invalid("card must be a mapping")
    card = dict(value)
    if not str(card.get("id") or "").strip():
        raise vol.Invalid("card needs an id")
    card["id"] = str(card["id"]).strip()
    if not card.get("title") and not card.get("body"):
        raise vol.Invalid("card needs a title or a body")
    return card


SHOW_CARD_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Required(ATTR_CARD): _card,
        vol.Optional(ATTR_FOCUS, default=False): cv.boolean,
        vol.Optional(ATTR_TTL): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_PRIORITY): vol.Coerce(int),
        vol.Optional(ATTR_NOTIFICATION_TITLE): cv.string,
        vol.Optional(ATTR_NOTIFICATION_BODY): cv.string,
    }
)

CLEAR_CARD_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Required(ATTR_CARD_ID): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Views and services live for the whole run; they answer 'not set up' without an entry."""
    hass.http.register_view(RegisterView())
    hass.http.register_view(CardsView())
    hass.http.register_view(ActionView())

    def hub() -> MiniemHub:
        current = hass.data.get(DOMAIN)
        if current is None:
            raise ServiceValidationError("Miniem is not set up")
        return current

    async def show_card(call: ServiceCall) -> None:
        current = hub()
        card = call.data[ATTR_CARD]
        focus = call.data[ATTR_FOCUS]
        title = call.data.get(ATTR_NOTIFICATION_TITLE) or card.get("title") or "Home Assistant"
        body = call.data.get(ATTR_NOTIFICATION_BODY) or card.get("subtitle")
        for device_id in current.resolve_targets(call.data.get(ATTR_DEVICE_ID)):
            current.put_card(device_id, card, call.data.get(ATTR_TTL), call.data.get(ATTR_PRIORITY))
            await current.async_ping(device_id, focus, title, body)

    async def clear_card(call: ServiceCall) -> None:
        current = hub()
        for device_id in current.resolve_targets(call.data.get(ATTR_DEVICE_ID)):
            if current.remove_card(device_id, call.data[ATTR_CARD_ID]):
                await current.async_ping(device_id, False, None, None)

    hass.services.async_register(DOMAIN, SERVICE_SHOW_CARD, show_card, schema=SHOW_CARD_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_CARD, clear_card, schema=CLEAR_CARD_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    fcm = None
    raw = entry.data.get(CONF_SERVICE_ACCOUNT)
    if raw:
        try:
            fcm = FcmClient(async_get_clientsession(hass), parse_service_account(raw))
        except ServiceAccountError:
            _LOGGER.error("The stored Firebase service account is unusable; cards work, pushes do not")
    hub = MiniemHub(hass, entry.entry_id, fcm)
    await hub.async_load()
    hass.data[DOMAIN] = hub
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.pop(DOMAIN, None)
    return True
