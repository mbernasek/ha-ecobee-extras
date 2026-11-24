"""The Aux heat max outdoor temperature number."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_component import DATA_INSTANCES
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import METRIC_SYSTEM
from pyecobee import InvalidTokenError
from pytest_homeassistant.common import async_fire_time_changed

from custom_components.ecobee_extras.number import _send

from .conftest import (
    ENTITY_ID,
    FURNACE_ID,
    HEAT_PUMP_ID,
    FakeEcobeeCloud,
    add_ecobee,
    add_extras,
    thermostat,
)


async def set_value(hass: HomeAssistant, value: float) -> None:
    """Change the number the way the dashboard does."""
    await hass.services.async_call(
        "number", "set_value", {"entity_id": ENTITY_ID, "value": value}, blocking=True
    )


async def poll(hass: HomeAssistant) -> None:
    """Let the entity's next scheduled update run."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()


async def test_reads_the_thermostats_value(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    await add_ecobee(hass, sign_in)
    await add_extras(hass)

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert float(state.state) == 50
    assert state.attributes["unit_of_measurement"] == "°F"
    assert state.attributes["min"] == 0
    assert state.attributes["max"] == 80
    assert state.attributes["step"] == 5
    assert state.attributes["staging_settings"] == {
        "auxMaxOutdoorTemp": 500,
        "auxOutdoorTempAlert": 500,
        "auxRuntimeAlert": 10800,
        "compressorProtectionMinTemp": 350,
        "coolStages": 1,
        "hasElectric": True,
        "hasHeatPump": True,
        "heatStages": 1,
        "stage1HeatingDifferentialTemp": 5,
    }


async def test_sits_on_the_thermostats_own_device(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    ecobee = await add_ecobee(hass, sign_in)
    extras = await add_extras(hass)

    entities = er.async_get(hass)
    ours = entities.async_get(ENTITY_ID)
    climate = entities.async_get("climate.hallway")
    assert ours is not None
    assert climate is not None
    assert ours.config_entry_id == extras.entry_id
    assert ours.unique_id == f"{HEAT_PUMP_ID}_aux_max_outdoor_temp"
    assert ours.entity_category is EntityCategory.CONFIG
    assert ours.device_id == climate.device_id

    # The device stays the ecobee integration's, and no second one appears.
    devices = list(dr.async_get(hass).devices)
    assert len(devices) == 1
    assert devices[0].config_entry_id == ecobee.entry_id


async def test_change_is_sent_and_confirmed(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    await add_ecobee(hass, sign_in)
    await add_extras(hass)

    await set_value(hass, 80)

    assert cloud.writes == [
        {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": HEAT_PUMP_ID,
            },
            "thermostat": {"settings": {"auxMaxOutdoorTemp": 800}},
        }
    ]
    assert cloud.setting() == 800
    assert float(hass.states.get(ENTITY_ID).state) == 80


async def test_value_is_rounded_to_a_whole_step(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    await add_ecobee(hass, sign_in)
    await add_extras(hass)

    await set_value(hass, 72)

    assert cloud.setting() == 700
    assert float(hass.states.get(ENTITY_ID).state) == 70


async def test_celsius_homes_are_converted(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    hass.config.units = METRIC_SYSTEM
    await add_ecobee(hass, sign_in)
    await add_extras(hass)
    assert float(hass.states.get(ENTITY_ID).state) == 10

    await set_value(hass, 25)

    # 25°C is 77°F, which becomes the nearest whole step, 75°F.
    assert cloud.setting() == 750


async def test_out_of_range_is_rejected_before_sending(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    await add_ecobee(hass, sign_in)
    await add_extras(hass)

    with pytest.raises(HomeAssistantError):
        await set_value(hass, 95)

    assert cloud.writes == []
    assert cloud.setting() == 500


async def test_refusal_carries_ecobees_reason(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    await add_ecobee(hass, sign_in)
    await add_extras(hass)
    cloud.on_write = "refuse"
    reads_before = cloud.reads

    with pytest.raises(HomeAssistantError, match=r"7: Validation error\. Not allowed"):
        await set_value(hass, 80)

    assert len(cloud.writes) == 1
    assert cloud.reads == reads_before
    assert float(hass.states.get(ENTITY_ID).state) == 50
    # The temporary log listener is gone again.
    assert logging.getLogger("pyecobee").handlers == []


async def test_accepted_but_not_applied_is_an_error(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    await add_ecobee(hass, sign_in)
    await add_extras(hass)
    cloud.on_write = "ignore"

    with pytest.raises(HomeAssistantError, match="still reports 50°F"):
        await set_value(hass, 80)

    assert len(cloud.writes) == 1
    assert float(hass.states.get(ENTITY_ID).state) == 50


async def test_unconfirmed_change_is_an_error(
    hass: HomeAssistant,
    cloud: FakeEcobeeCloud,
    sign_in: dict[str, str],
    freezer: FrozenDateTimeFactory,
) -> None:
    await add_ecobee(hass, sign_in)
    await add_extras(hass)
    cloud.reads_fail = True

    with pytest.raises(HomeAssistantError, match="could not read the thermostat back"):
        await set_value(hass, 80)

    assert cloud.setting() == 800

    # Once ecobee answers again, the entity catches up at the ecobee
    # integration's next refresh, at most three minutes later.
    cloud.reads_fail = False
    freezer.tick(timedelta(seconds=181))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert float(hass.states.get(ENTITY_ID).state) == 80


async def test_only_heat_pump_thermostats_get_the_number(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    cloud.thermostats.append(thermostat(FURNACE_ID, "Upstairs", heat_pump=False))
    await add_ecobee(hass, sign_in)
    await add_extras(hass)

    assert hass.states.get("climate.upstairs") is not None
    assert hass.states.get(ENTITY_ID) is not None
    assert sorted(hass.states.async_entity_ids("number")) == [
        ENTITY_ID,
        "number.hallway_compressor_minimum_temperature",
        "number.hallway_fan_minimum_on_time",
        "number.upstairs_fan_minimum_on_time",
    ]


async def test_change_goes_to_the_right_thermostat(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    cloud.thermostats.insert(0, thermostat(FURNACE_ID, "Upstairs", heat_pump=False))
    await add_ecobee(hass, sign_in)
    await add_extras(hass)

    await set_value(hass, 65)

    assert cloud.writes[0]["selection"]["selectionMatch"] == HEAT_PUMP_ID
    assert cloud.setting(HEAT_PUMP_ID) == 650
    assert cloud.setting(FURNACE_ID) is None


async def test_offline_thermostat_is_unavailable(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    cloud.thermostats[0]["runtime"]["connected"] = False
    await add_ecobee(hass, sign_in)
    await add_extras(hass)

    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


async def test_keeps_working_after_ecobee_reloads(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    ecobee = await add_ecobee(hass, sign_in)
    extras = await add_extras(hass)

    await hass.config_entries.async_unload(ecobee.entry_id)
    await hass.async_block_till_done()
    await poll(hass)
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

    cloud.thermostats[0]["settings"]["auxMaxOutdoorTemp"] = 350
    await hass.config_entries.async_setup(ecobee.entry_id)
    await hass.async_block_till_done()
    await poll(hass)
    assert ecobee.state is ConfigEntryState.LOADED
    assert extras.state is ConfigEntryState.LOADED
    assert float(hass.states.get(ENTITY_ID).state) == 35

    await set_value(hass, 80)
    assert cloud.setting() == 800
    assert float(hass.states.get(ENTITY_ID).state) == 80


async def test_a_failing_ecobee_refresh_is_not_fatal(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    ecobee = await add_ecobee(hass, sign_in)
    await add_extras(hass)
    data_class = type(ecobee.runtime_data)

    with patch.object(data_class, "update", AsyncMock(side_effect=RuntimeError("no"))):
        await poll(hass)
        assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

        # A change still goes out, and says it could not be confirmed.
        with pytest.raises(HomeAssistantError, match="could not read the thermostat"):
            await (
                hass.data[DATA_INSTANCES]["number"]
                .get_entity(ENTITY_ID)
                .async_set_native_value(80)
            )
        assert cloud.setting() == 800

    await poll(hass)
    assert hass.states.get(ENTITY_ID).state != STATE_UNAVAILABLE


async def test_change_fails_cleanly_while_ecobee_is_unloaded(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    ecobee = await add_ecobee(hass, sign_in)
    await add_extras(hass)
    entity = hass.data[DATA_INSTANCES]["number"].get_entity(ENTITY_ID)

    await hass.config_entries.async_unload(ecobee.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError, match="not loaded"):
        await entity.async_set_native_value(80)
    assert cloud.writes == []


async def test_library_error_becomes_a_readable_failure(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    await add_ecobee(hass, sign_in)
    await add_extras(hass)

    with (
        patch(
            "pyecobee.Ecobee.set_aux_maxtemp_threshold",
            side_effect=InvalidTokenError("ecobee tokens invalid"),
        ),
        pytest.raises(HomeAssistantError, match="ecobee tokens invalid"),
    ):
        await set_value(hass, 80)

    assert cloud.writes == []
    assert float(hass.states.get(ENTITY_ID).state) == 50


async def test_no_number_when_the_thermostat_lacks_the_setting(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    del cloud.thermostats[0]["settings"]["auxMaxOutdoorTemp"]
    await add_ecobee(hass, sign_in)
    extras = await add_extras(hass)

    assert extras.state is ConfigEntryState.LOADED
    assert hass.states.get(ENTITY_ID) is None


async def test_unavailable_once_the_thermostat_is_gone(
    hass: HomeAssistant,
    cloud: FakeEcobeeCloud,
    sign_in: dict[str, str],
    freezer: FrozenDateTimeFactory,
) -> None:
    await add_ecobee(hass, sign_in)
    await add_extras(hass)

    cloud.thermostats[0] = thermostat(FURNACE_ID, "Upstairs", heat_pump=False)
    freezer.tick(timedelta(seconds=181))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


async def test_works_without_a_climate_entity_to_attach_to(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    with patch("homeassistant.components.ecobee.PLATFORMS", [Platform.NUMBER]):
        await add_ecobee(hass, sign_in)
        await add_extras(hass)

        entity_id = "number.aux_heat_max_outdoor_temperature"
        assert float(hass.states.get(entity_id).state) == 50
        assert er.async_get(hass).async_get(entity_id).device_id is None


class _FakeLibrary:
    """Just enough of the ecobee library for the send step."""

    def __init__(self, identifiers: list[str], log: str | None = None) -> None:
        self.thermostats = [{"identifier": identifier} for identifier in identifiers]
        self.calls: list[tuple[int, Any]] = []
        self._log = log

    def set_aux_maxtemp_threshold(self, index: int, threshold: Any) -> None:
        self.calls.append((index, threshold))
        if self._log:
            logging.getLogger("pyecobee").error(self._log)


def test_send_refuses_when_the_thermostat_moved() -> None:
    library = _FakeLibrary([FURNACE_ID, HEAT_PUMP_ID])

    with pytest.raises(HomeAssistantError, match="list changed"):
        _send(library, 0, HEAT_PUMP_ID, 80)
    with pytest.raises(HomeAssistantError, match="list changed"):
        _send(library, 5, HEAT_PUMP_ID, 80)

    assert library.calls == []


def test_send_reports_what_the_library_logged() -> None:
    assert _send(_FakeLibrary([HEAT_PUMP_ID]), 0, HEAT_PUMP_ID, 80) is None

    library = _FakeLibrary([HEAT_PUMP_ID], log="Error from ecobee: 2: Not authorized.")
    assert (
        _send(library, 0, HEAT_PUMP_ID, 80) == "Error from ecobee: 2: Not authorized."
    )
    assert library.calls == [(0, 80)]
