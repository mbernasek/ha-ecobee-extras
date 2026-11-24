# ecobee extras for Home Assistant

Adds one thermostat setting that the built-in ecobee integration leaves out:
**Aux heat max outdoor temperature**.

A heat pump thermostat will not run auxiliary heat while the outdoor
temperature is above this threshold. ecobee offers the setting on the
thermostat's own screen (Menu, Settings, Installation Settings, Thresholds).
This integration puts it in Home Assistant as a number, so it can be read and
changed from anywhere.

## How it works

- It has no sign-in of its own. It uses the session of the built-in ecobee
  integration, which must already be set up.
- It adds one number to each heat pump thermostat that reports the setting.
  The number sits on the thermostat's existing device, under Configuration.
- A change is sent with the ecobee library that ships with Home Assistant,
  through its `set_aux_maxtemp_threshold` method. ecobee's API documentation
  lists the underlying setting, `auxMaxOutdoorTemp`, as writable.
- After sending, it reads the thermostat back. The change counts as made only
  when the thermostat reports the new value. Otherwise you get an error, with
  ecobee's own reason when ecobee gave one.

## Requirements

- Home Assistant 2026.11 or later.
- The built-in ecobee integration, set up and working.
- A thermostat that controls a heat pump with auxiliary heat.

## Install

1. Add this repository to Home Assistant as a custom integration and download
   it.
2. Restart Home Assistant.
3. Go to Settings, Devices & services, Add integration, and pick
   **ecobee extras**. There is nothing to enter.

Manual install: copy `custom_components/ecobee_extras` into the
`custom_components` folder of your Home Assistant configuration, then restart.

## Use

Open the thermostat's device page. **Aux heat max outdoor temperature** is
under Configuration. It accepts 0 to 80°F in steps of 5.

It can also be set from an automation or script:

```yaml
action: number.set_value
target:
  entity_id: number.my_thermostat_aux_heat_max_outdoor_temperature
data:
  value: 50
```

The number also carries a `staging_settings` attribute with the thermostat's
related heat pump and auxiliary heat settings, for reference.

## Before you change it

- Write down the starting value. This is an installer setting, and the
  original is the one to go back to.
- Auxiliary heat usually costs several times more to run than the heat pump.
  A higher threshold lets the thermostat use it in milder weather.
- The threshold only permits auxiliary heat. Whether the thermostat then runs
  it is still decided by the thermostat's own staging.
- Check the number again a few minutes after a change. The thermostat has the
  final say, and Home Assistant shows what it reports.

## Development

Needs Python 3.14.

```shell
uv pip install -r requirements-dev.txt
pytest
ruff check . && ruff format --check .
```

The tests run the real built-in ecobee integration and the real ecobee library
against a stand-in for ecobee's cloud. Tested with Home Assistant 2026.11.2.

This project is not affiliated with ecobee.
