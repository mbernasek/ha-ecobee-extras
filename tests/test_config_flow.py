"""Adding ecobee extras from the integrations page."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.translation import async_get_translations

from custom_components.ecobee_extras.const import DOMAIN

from .conftest import FakeEcobeeCloud, add_ecobee, add_extras


async def test_one_confirmation_step(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    await add_ecobee(hass, sign_in)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "ecobee extras"
    assert result["data"] == {}


async def test_needs_the_ecobee_integration(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "ecobee_not_configured"


async def test_only_one_instance(
    hass: HomeAssistant, cloud: FakeEcobeeCloud, sign_in: dict[str, str]
) -> None:
    await add_ecobee(hass, sign_in)
    await add_extras(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_every_message_has_text(hass: HomeAssistant) -> None:
    texts = await async_get_translations(hass, "en", "config", [DOMAIN])

    for key in (
        "step.user.title",
        "step.user.description",
        "abort.ecobee_not_configured",
        "abort.single_instance_allowed",
    ):
        assert texts.get(f"component.{DOMAIN}.config.{key}"), key
