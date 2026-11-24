"""
Number entity for ecobee's Aux Heat Max Outdoor Temperature threshold.

The thermostat will not run auxiliary heat while the outdoor temperature is
above this value. ecobee offers the setting on the thermostat's own screen
only. Its API accepts it, and the ecobee library that Home Assistant ships can
send it, but the built-in integration has no entity for it.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device import async_entity_id_to_device

from . import loaded_ecobee_data
from .const import ATTR_STAGING_SETTINGS, ECOBEE_DOMAIN, SETTING_AUX_MAX_OUTDOOR_TEMP

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceEntry
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

_LOGGER = logging.getLogger(__name__)

# Reads come from the data the ecobee integration already holds, which it
# refreshes at most every three minutes, so polling adds no requests.
SCAN_INTERVAL = timedelta(seconds=60)
PARALLEL_UPDATES = 1

# Seconds to wait before each read-back after a change.
CONFIRM_DELAYS: tuple[float, ...] = (2.0, 4.0, 8.0)

# Degrees Fahrenheit. The step matches the built-in compressor threshold.
MIN_DEGREES = 0
MAX_DEGREES = 80
STEP_DEGREES = 5

# The ecobee library logs its failures under this name instead of raising them.
_LIBRARY_LOGGER = "pyecobee"

_STAGING_KEYS = re.compile(r"aux|stage|compressor|heatpump|haselectric", re.IGNORECASE)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,  # noqa: ARG001
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add one number per heat pump thermostat that reports the setting."""
    data = loaded_ecobee_data(hass)
    thermostats = (data.ecobee.thermostats or []) if data is not None else []
    async_add_entities(
        EcobeeAuxMaxOutdoorTemp(hass, thermostat)
        for thermostat in thermostats
        if _has_setting(thermostat)
    )


def _has_setting(thermostat: dict[str, Any]) -> bool:
    """Return True for a heat pump thermostat that reports the threshold."""
    settings = thermostat.get("settings") or {}
    return bool(settings.get("hasHeatPump")) and _reported_tenths(settings) is not None


def _reported_tenths(settings: dict[str, Any]) -> int | float | None:
    """Return the threshold as ecobee reports it: tenths of a degree."""
    raw = settings.get(SETTING_AUX_MAX_OUTDOOR_TEMP)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return raw


def _ecobee_device(hass: HomeAssistant, identifier: Any) -> DeviceEntry | None:
    """
    Return the thermostat's existing device, so the entity sits beside it.

    The device belongs to the ecobee integration. It is found through the
    thermostat's climate entity, whose unique id is the thermostat identifier.
    """
    entity_id = er.async_get(hass).async_get_entity_id(
        "climate", ECOBEE_DOMAIN, str(identifier)
    )
    if entity_id is None:
        return None
    return async_entity_id_to_device(hass, entity_id)


class _LibraryErrors(logging.Handler):
    """Collect what the ecobee library logs as errors on the calling thread."""

    def __init__(self) -> None:
        """Start collecting for the current thread."""
        super().__init__(level=logging.ERROR)
        self._thread = threading.get_ident()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Keep the message if this thread logged it."""
        if record.thread == self._thread:
            self.messages.append(record.getMessage())


def _send(ecobee: Any, index: int, identifier: Any, degrees: int) -> str | None:
    """
    Send the new threshold. Runs in the executor.

    Returns None when the library reported no problem, otherwise the error it
    logged. The library does not raise when ecobee refuses a change.
    """
    thermostats = ecobee.thermostats or []
    if index >= len(thermostats) or thermostats[index].get("identifier") != identifier:
        msg = "The thermostat list changed while sending. Try again."
        raise HomeAssistantError(msg)

    errors = _LibraryErrors()
    library_logger = logging.getLogger(_LIBRARY_LOGGER)
    library_logger.addHandler(errors)
    try:
        ecobee.set_aux_maxtemp_threshold(index, degrees)
    finally:
        library_logger.removeHandler(errors)
    return errors.messages[-1] if errors.messages else None


class EcobeeAuxMaxOutdoorTemp(NumberEntity):
    """Outdoor temperature above which the thermostat will not run aux heat."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_icon = "mdi:thermometer-chevron-up"
    _attr_mode = NumberMode.BOX
    _attr_name = "Aux heat max outdoor temperature"
    _attr_native_max_value = MAX_DEGREES
    _attr_native_min_value = MIN_DEGREES
    _attr_native_step = STEP_DEGREES
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _unrecorded_attributes = frozenset({ATTR_STAGING_SETTINGS})

    def __init__(self, hass: HomeAssistant, thermostat: dict[str, Any]) -> None:
        """Initialize from the thermostat data the ecobee integration holds."""
        self._identifier = thermostat["identifier"]
        self._attr_unique_id = f"{self._identifier}_aux_max_outdoor_temp"
        self.device_entry = _ecobee_device(hass, self._identifier)
        self._apply(thermostat)

    def _locate(self) -> tuple[Any, int, dict[str, Any]] | None:
        """Return the live ecobee data, and this thermostat's place in it."""
        data = loaded_ecobee_data(self.hass)
        if data is None:
            return None
        for index, thermostat in enumerate(data.ecobee.thermostats or []):
            if thermostat.get("identifier") == self._identifier:
                return data, index, thermostat
        return None

    def _apply(self, thermostat: dict[str, Any]) -> None:
        """Copy the thermostat's reported values onto the entity."""
        settings = thermostat.get("settings") or {}
        tenths = _reported_tenths(settings)
        self._attr_native_value = None if tenths is None else tenths / 10
        runtime = thermostat.get("runtime") or {}
        self._attr_available = bool(runtime.get("connected", True))
        self._attr_extra_state_attributes = {
            ATTR_STAGING_SETTINGS: {
                key: settings[key]
                for key in sorted(settings)
                if _STAGING_KEYS.search(key)
            }
        }

    async def async_update(self) -> None:
        """Read the threshold from the ecobee integration's data."""
        located = self._locate()
        if located is not None:
            try:
                await located[0].update()
            except Exception as err:
                # The ecobee integration reports its own sign-in problems.
                _LOGGER.debug("ecobee refresh failed: %s", err)
                located = None
            else:
                # A refresh replaces the thermostat list, so look again.
                located = self._locate()
        if located is None:
            self._attr_available = False
            return
        self._apply(located[2])

    async def async_set_native_value(self, value: float) -> None:
        """Change the threshold, then confirm the thermostat reports it."""
        located = self._locate()
        if located is None:
            msg = (
                "The ecobee integration is not loaded, so the thermostat can't "
                "be reached."
            )
            raise HomeAssistantError(msg)
        data, index, _ = located
        degrees = round(value / STEP_DEGREES) * STEP_DEGREES

        try:
            refusal = await self.hass.async_add_executor_job(
                _send, data.ecobee, index, self._identifier, degrees
            )
        except HomeAssistantError:
            raise
        except Exception as err:
            # The library raises its own errors when the sign-in is rejected.
            msg = f"ecobee did not take the change: {err}"
            raise HomeAssistantError(msg) from err
        if refusal is not None:
            msg = f"ecobee did not take the change. {refusal}"
            raise HomeAssistantError(msg)

        reported, refreshed = await self._async_read_back(degrees * 10)
        self.async_write_ha_state()
        if reported == degrees * 10:
            _LOGGER.debug("Aux heat max outdoor temperature is now %s°F", degrees)
            return
        if not refreshed:
            msg = (
                f"The change to {degrees}°F was sent, but Home Assistant could "
                "not read the thermostat back to confirm it."
            )
        else:
            shown = "no value" if reported is None else f"{reported / 10:g}°F"
            msg = (
                f"The change to {degrees}°F was sent without an error, but the "
                f"thermostat still reports {shown}."
            )
        raise HomeAssistantError(msg)

    async def _async_read_back(self, target: int) -> tuple[int | float | None, bool]:
        """
        Refresh until the thermostat reports the target, or the tries run out.

        Returns what the thermostat last reported, and whether any refresh got
        fresh data from ecobee.
        """
        reported: int | float | None = None
        refreshed = False
        for delay in CONFIRM_DELAYS:
            await asyncio.sleep(delay)
            located = self._locate()
            if located is None:
                continue
            data = located[0]
            before = data.ecobee.thermostats
            try:
                await data.update(no_throttle=True)
            except Exception as err:
                _LOGGER.debug("ecobee refresh failed: %s", err)
                continue
            located = self._locate()
            if located is None:
                continue
            # The library swaps in a new list only when a refresh succeeds.
            refreshed = refreshed or located[0].ecobee.thermostats is not before
            self._apply(located[2])
            reported = _reported_tenths(located[2].get("settings") or {})
            if reported == target:
                break
        return reported, refreshed
