"""
Fixtures for the ecobee extras tests.

The tests run the real built-in ecobee integration and the real ecobee library
against a stand-in for ecobee's cloud, so what is checked is the request that
would leave Home Assistant. Every identifier and value here is invented.
"""

from __future__ import annotations

import copy
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant.common import MockConfigEntry
from requests_mock import Mocker

from custom_components.ecobee_extras.const import DOMAIN

THERMOSTAT_URL = "https://api.ecobee.com/1/thermostat"
API_KEY_TOKEN_URL = "https://api.ecobee.com/token"  # noqa: S105
WEB_LOGIN_TOKEN_URL = "https://auth.ecobee.com/oauth/token"  # noqa: S105

HEAT_PUMP_ID = "100200300400"
FURNACE_ID = "100200300401"

ENTITY_ID = "number.hallway_aux_heat_max_outdoor_temperature"

SIGN_INS: dict[str, dict[str, str]] = {
    "api_key": {"api_key": "test-key", "refresh_token": "test-refresh"},
    "web_login": {
        "username": "someone@example.com",
        "password": "test-password",
        "refresh_token": "test-refresh",
    },
}


def thermostat(identifier: str, name: str, *, heat_pump: bool = True) -> dict[str, Any]:
    """Build one thermostat the way ecobee's API returns it."""
    settings: dict[str, Any] = {
        "hvacMode": "heat",
        "heatStages": 1,
        "coolStages": 1,
        "fanMinOnTime": 0,
        "heatCoolMinDelta": 50,
        "holdAction": "nextTransition",
        "ventilatorType": "none",
        "ventilatorMinOnTimeHome": 20,
        "ventilatorMinOnTimeAway": 20,
        "isVentilatorTimerOn": False,
        "hasHumidifier": False,
        "humidifierMode": "off",
        "humidity": "36",
        "hasHeatPump": heat_pump,
    }
    if heat_pump:
        settings |= {
            "hasElectric": True,
            "compressorProtectionMinTemp": 350,
            "auxMaxOutdoorTemp": 500,
            "auxRuntimeAlert": 10800,
            "auxOutdoorTempAlert": 500,
            "stage1HeatingDifferentialTemp": 5,
        }
    return {
        "identifier": identifier,
        "name": name,
        "modelNumber": "nikeSmart",
        "program": {
            "climates": [{"name": "Home", "climateRef": "home", "sensors": []}],
            "currentClimateRef": "home",
        },
        "runtime": {
            "connected": True,
            "actualTemperature": 700,
            "actualHumidity": 40,
            "desiredHeat": 680,
            "desiredCool": 760,
            "desiredFanMode": "auto",
            "desiredHumidity": 36,
        },
        "settings": settings,
        "equipmentStatus": "",
        "events": [],
        "remoteSensors": [],
    }


class FakeEcobeeCloud:
    """Answer the ecobee requests Home Assistant makes during the tests."""

    def __init__(self, mocker: Mocker) -> None:
        """Register the handlers and start with one heat pump thermostat."""
        self.thermostats = [thermostat(HEAT_PUMP_ID, "Hallway")]
        self.writes: list[dict[str, Any]] = []
        self.reads = 0
        self.on_write = "apply"  # or "ignore" or "refuse"
        self.reads_fail = False
        self.sign_in_fails = False
        mocker.get(THERMOSTAT_URL, json=self._read)
        mocker.post(THERMOSTAT_URL, json=self._write)
        mocker.post(API_KEY_TOKEN_URL, json=self._token)
        mocker.post(WEB_LOGIN_TOKEN_URL, json=self._token)

    def setting(self, identifier: str = HEAT_PUMP_ID) -> Any:
        """Return the threshold the cloud currently holds for a thermostat."""
        for item in self.thermostats:
            if item["identifier"] == identifier:
                return item["settings"].get("auxMaxOutdoorTemp")
        return None

    def _read(self, request: Any, context: Any) -> dict[str, Any]:
        self.reads += 1
        if self.reads_fail:
            context.status_code = 500
            return {"status": {"code": 3, "message": "Processing error."}}
        return {
            "thermostatList": copy.deepcopy(self.thermostats),
            "status": {"code": 0, "message": ""},
        }

    def _write(self, request: Any, context: Any) -> dict[str, Any]:
        body = request.json()
        self.writes.append(body)
        if self.on_write == "refuse":
            context.status_code = 500
            return {"status": {"code": 7, "message": "Validation error. Not allowed."}}
        if self.on_write == "apply":
            for item in self.thermostats:
                if item["identifier"] == body["selection"]["selectionMatch"]:
                    item["settings"].update(body["thermostat"]["settings"])
        return {"status": {"code": 0, "message": ""}}

    def _token(self, request: Any, context: Any) -> dict[str, Any]:
        if self.sign_in_fails:
            context.status_code = 503
            return {}
        return {
            "access_token": "test-access",
            "token_type": "Bearer",
            "expires_in": 3599,
            "refresh_token": "test-refresh",
            "scope": "smartWrite",
        }


@pytest.fixture(autouse=True)
def fahrenheit(hass: HomeAssistant) -> None:
    """Show temperatures in Fahrenheit, the unit ecobee's API works in."""
    hass.config.units = US_CUSTOMARY_SYSTEM


@pytest.fixture(autouse=True)
def fewer_ecobee_platforms() -> Generator[None]:
    """Keep the built-in integration to the platforms these tests rely on."""
    with patch(
        "homeassistant.components.ecobee.PLATFORMS",
        [Platform.CLIMATE, Platform.NUMBER],
    ):
        yield


@pytest.fixture(autouse=True)
def no_read_back_delay() -> Generator[None]:
    """Skip the pauses between read-backs."""
    with patch("custom_components.ecobee_extras.number.CONFIRM_DELAYS", (0, 0, 0)):
        yield


@pytest.fixture
def cloud(requests_mock: Mocker) -> FakeEcobeeCloud:
    """Stand in for ecobee's cloud."""
    return FakeEcobeeCloud(requests_mock)


@pytest.fixture(params=sorted(SIGN_INS))
def sign_in(request: pytest.FixtureRequest) -> dict[str, str]:
    """Run each test with both ways the ecobee integration can sign in."""
    return dict(SIGN_INS[request.param])


async def add_ecobee(hass: HomeAssistant, sign_in: dict[str, str]) -> MockConfigEntry:
    """Set up the built-in ecobee integration."""
    entry = MockConfigEntry(domain="ecobee", title="ecobee", data=sign_in)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def add_extras(hass: HomeAssistant) -> MockConfigEntry:
    """Set up ecobee extras."""
    entry = MockConfigEntry(domain=DOMAIN, title="ecobee extras", data={})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
