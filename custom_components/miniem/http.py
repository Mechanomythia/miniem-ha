"""The API the launcher talks to. Every view requires Home Assistant's own auth."""

from __future__ import annotations

from http import HTTPStatus
import logging
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from homeassistant.helpers.http import KEY_HASS

from .const import DOMAIN, EVENT_ACTION

_LOGGER = logging.getLogger(__name__)


def _hub(request: web.Request):
    hass = request.app[KEY_HASS]
    return hass, hass.data.get(DOMAIN)


def _not_ready() -> web.Response:
    return web.json_response({"error": "Miniem is not set up"}, status=HTTPStatus.SERVICE_UNAVAILABLE)


class RegisterView(HomeAssistantView):
    url = "/api/miniem/register"
    name = "api:miniem:register"

    async def post(self, request: web.Request) -> web.Response:
        hass, hub = _hub(request)
        if hub is None:
            return _not_ready()
        try:
            body: dict[str, Any] = await request.json()
        except ValueError:
            return self.json_message("Invalid JSON", HTTPStatus.BAD_REQUEST)
        device_id = str(body.get("device_id") or "").strip()
        if not device_id:
            return self.json_message("device_id is required", HTTPStatus.BAD_REQUEST)
        hub.register(
            device_id=device_id,
            name=str(body.get("name") or "Miniem phone")[:100],
            push_token=body.get("push_token") or None,
            app_version=body.get("app_version"),
            platform="ios" if body.get("platform") == "ios" else "android",
        )
        return self.json({"ok": True})


class CardsView(HomeAssistantView):
    url = "/api/miniem/cards"
    name = "api:miniem:cards"

    async def get(self, request: web.Request) -> web.Response:
        hass, hub = _hub(request)
        if hub is None:
            return _not_ready()
        device_id = request.query.get("device_id", "")
        return self.json({"cards": hub.cards_for(device_id)})


class ActionView(HomeAssistantView):
    url = "/api/miniem/action"
    name = "api:miniem:action"

    async def post(self, request: web.Request) -> web.Response:
        hass, hub = _hub(request)
        if hub is None:
            return _not_ready()
        try:
            body: dict[str, Any] = await request.json()
        except ValueError:
            return self.json_message("Invalid JSON", HTTPStatus.BAD_REQUEST)

        device_id = str(body.get("device_id") or "")
        card_id = str(body.get("card_id") or "")
        kind = body.get("type")
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        values = body.get("values") if isinstance(body.get("values"), dict) else {}
        if not card_id or kind not in ("event", "service", "dismiss"):
            return self.json_message("card_id and a known type are required", HTTPStatus.BAD_REQUEST)

        user = request.get("hass_user")
        context = Context(user_id=user.id if user else None)
        action = {"event": body.get("name"), "service": body.get("service"), "dismiss": "dismiss"}[kind]
        if not action:
            return self.json_message("The action has no name", HTTPStatus.BAD_REQUEST)

        hass.bus.async_fire(
            EVENT_ACTION,
            {
                "device_id": hub.ha_device_id(device_id),
                "device_name": hub.devices.get(device_id, {}).get("name"),
                "card_id": card_id,
                "action": action,
                "data": data,
                "values": values,
            },
            context=context,
        )

        if kind == "service":
            domain, _, service = str(action).partition(".")
            try:
                await hass.services.async_call(domain, service, data, blocking=False, context=context)
            except (ServiceNotFound, HomeAssistantError, ValueError) as err:
                return self.json_message(f"Service call failed: {err}", HTTPStatus.BAD_REQUEST)

        if body.get("dismiss", True):
            hub.remove_card(device_id, card_id)
        return self.json({"ok": True})
