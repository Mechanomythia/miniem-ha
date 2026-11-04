"""The integration's state: registered phones and the cards waiting for them."""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_KEY, STORAGE_VERSION
from .fcm import FcmClient, TokenUnregistered

_LOGGER = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


class MiniemHub:
    """Phones by Miniem's own device id, and per phone its cards by card id."""

    def __init__(self, hass: HomeAssistant, entry_id: str, fcm: FcmClient | None) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.fcm = fcm
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.devices: dict[str, dict[str, Any]] = {}
        self.cards: dict[str, dict[str, dict[str, Any]]] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.devices = data.get("devices", {})
        self.cards = data.get("cards", {})
        registry = dr.async_get(self.hass)
        for device_id, device in self.devices.items():
            self._register_device(registry, device_id, device)

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(lambda: {"devices": self.devices, "cards": self.cards}, 1)

    @callback
    def _register_device(self, registry: dr.DeviceRegistry, device_id: str, device: dict[str, Any]) -> None:
        registry.async_get_or_create(
            config_entry_id=self.entry_id,
            identifiers={(DOMAIN, device_id)},
            name=device.get("name") or "Miniem phone",
            manufacturer="Miniem",
            model="Launcher",
            sw_version=device.get("app_version"),
        )

    # ---- phones -------------------------------------------------------------------

    @callback
    def register(self, device_id: str, name: str, push_token: str | None, app_version: str | None) -> None:
        self.devices[device_id] = {
            "name": name,
            "push_token": push_token,
            "app_version": app_version,
            "registered_at": _now_ms(),
        }
        self._register_device(dr.async_get(self.hass), device_id, self.devices[device_id])
        self._save()

    @callback
    def resolve_targets(self, ha_device_ids: list[str] | None) -> list[str]:
        """Home Assistant device registry ids → Miniem device ids. None means every phone."""
        if not ha_device_ids:
            return list(self.devices)
        registry = dr.async_get(self.hass)
        targets = []
        for ha_id in ha_device_ids:
            entry = registry.async_get(ha_id)
            if entry is None:
                continue
            targets += [ident for domain, ident in entry.identifiers if domain == DOMAIN and ident in self.devices]
        return targets

    @callback
    def ha_device_id(self, device_id: str) -> str | None:
        # Looked up among this entry's own devices: identifiers are only unique per
        # config entry now, and async_get_device is deprecated for that reason.
        for entry in dr.async_entries_for_config_entry(dr.async_get(self.hass), self.entry_id):
            if (DOMAIN, device_id) in entry.identifiers:
                return entry.id
        return None

    # ---- cards --------------------------------------------------------------------

    @callback
    def cards_for(self, device_id: str) -> list[dict[str, Any]]:
        now = _now_ms()
        cards = self.cards.get(device_id, {})
        expired = [cid for cid, card in cards.items() if card.get("expires_at") and card["expires_at"] <= now]
        for cid in expired:
            del cards[cid]
        if expired:
            self._save()
        return list(cards.values())

    @callback
    def put_card(self, device_id: str, card: dict[str, Any], ttl: int | None, priority: int | None) -> None:
        now = _now_ms()
        stored = dict(card)
        stored["updated_at"] = now
        if ttl:
            stored["expires_at"] = now + ttl * 1000
        else:
            stored.pop("expires_at", None)
        if priority is not None:
            stored["priority"] = priority
        self.cards.setdefault(device_id, {})[stored["id"]] = stored
        self._save()

    @callback
    def remove_card(self, device_id: str, card_id: str) -> bool:
        removed = self.cards.get(device_id, {}).pop(card_id, None) is not None
        if removed:
            self._save()
        return removed

    async def async_ping(self, device_id: str, focus: bool, title: str | None, body: str | None) -> None:
        """Tell a phone its cards changed. Silently nothing without push."""
        device = self.devices.get(device_id)
        if not device or not device.get("push_token") or self.fcm is None:
            return
        data = {"kind": "cards", "focus": "true" if focus else "false"}
        if title:
            data["title"] = title
        if body:
            data["body"] = body
        try:
            await self.fcm.send(device["push_token"], data)
        except TokenUnregistered:
            _LOGGER.info("Push token for %s is gone; it re-registers when the launcher next opens", device.get("name"))
            device["push_token"] = None
            self._save()
        except Exception:  # noqa: BLE001 - a failed push must never fail the automation
            _LOGGER.exception("Could not push to %s", device.get("name"))
