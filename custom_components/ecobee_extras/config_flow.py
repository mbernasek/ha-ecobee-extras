"""Config flow for ecobee extras. There is nothing to enter."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, ECOBEE_DOMAIN


class EcobeeExtrasConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add ecobee extras with a single confirmation step."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm, then create the entry. The manifest allows only one."""
        if not self.hass.config_entries.async_entries(ECOBEE_DOMAIN):
            return self.async_abort(reason="ecobee_not_configured")

        if user_input is None:
            return self.async_show_form(step_id="user")

        return self.async_create_entry(title="ecobee extras", data={})
