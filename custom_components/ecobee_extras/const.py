"""Constants for ecobee extras."""

from typing import Final

DOMAIN: Final = "ecobee_extras"

# The built-in integration whose session and data this add-on reuses.
ECOBEE_DOMAIN: Final = "ecobee"

# ecobee stores this threshold in tenths of a degree Fahrenheit.
SETTING_AUX_MAX_OUTDOOR_TEMP: Final = "auxMaxOutdoorTemp"

ATTR_STAGING_SETTINGS: Final = "staging_settings"
