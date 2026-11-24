"""Setting up and removing ecobee extras."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from .conftest import ENTITY_ID, FakeEcobeeCloud, add_ecobee, add_extras


async def test_waits_until_ecobee_has_loaded(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    cloud.sign_in_fails = True
    ecobee = await add_ecobee(hass, sign_in)
    extras = await add_extras(hass)
    assert ecobee.state is not ConfigEntryState.LOADED
    assert extras.state is ConfigEntryState.SETUP_RETRY
    assert hass.states.get(ENTITY_ID) is None

    cloud.sign_in_fails = False
    await hass.config_entries.async_reload(ecobee.entry_id)
    await hass.async_block_till_done()
    assert ecobee.state is ConfigEntryState.LOADED

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert extras.state is ConfigEntryState.LOADED
    assert float(hass.states.get(ENTITY_ID).state) == 50


async def test_setting_up_extras_brings_up_ecobee_first(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    """At startup Home Assistant may reach this integration before ecobee."""
    ecobee = MockConfigEntry(domain="ecobee", title="ecobee", data=sign_in)
    ecobee.add_to_hass(hass)

    extras = await add_extras(hass)

    assert ecobee.state is ConfigEntryState.LOADED
    assert extras.state is ConfigEntryState.LOADED
    assert float(hass.states.get(ENTITY_ID).state) == 50


async def test_removing_extras_leaves_ecobee_alone(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    ecobee = await add_ecobee(hass, sign_in)
    extras = await add_extras(hass)

    await hass.config_entries.async_remove(extras.entry_id)
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get(ENTITY_ID) is None
    assert ecobee.state is ConfigEntryState.LOADED
    assert hass.states.get("climate.hallway") is not None
    assert len(list(dr.async_get(hass).devices)) == 1
    assert cloud.writes == []
