"""
ecobee extras.

Adds thermostat settings that the built-in ecobee integration does not expose.
It has no connection of its own: it reuses the built-in integration's signed-in
session, so the ecobee integration must already be set up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady

from .const import ECOBEE_DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

PLATFORMS = [Platform.NUMBER]


def loaded_ecobee_data(hass: HomeAssistant) -> Any | None:
    """
    Return the built-in ecobee integration's live data object.

    Looked up on every use instead of being kept, because the built-in
    integration replaces this object whenever it reloads. Returns None while
    the ecobee integration is not loaded.
    """
    for entry in hass.config_entries.async_entries(ECOBEE_DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        data = getattr(entry, "runtime_data", None)
        if data is not None and getattr(data, "ecobee", None) is not None:
            return data
    return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ecobee extras once the ecobee integration is loaded."""
    if loaded_ecobee_data(hass) is None:
        msg = "The ecobee integration is not loaded yet"
        raise ConfigEntryNotReady(msg)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload ecobee extras."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
