![Logo](doc/logo.png)

[![hacs_badge]](https://github.com/hacs/integration)
![analytics_badge]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

## Description

This integration adds a platform entity that provides sensors to monitor energy consumption.
In order to use this in a meaningful way, a meter reader for the total power usage of the HA installation is needed,
typically this means that you have a meter reader installed on your AMS meter.

This integration was written as a stopgap for missing sensors after moving away from Tibber.  It provides similar sensors
as what you can get from their HA integration and from their GraphQl API.  If you want to ensure that you do not exceed
a grip energy step level, this integration will provide you with the tools to succeed.

## Installation

This sensor can either be installed manually, or via HACS(recommended)

### Manual install

1.  Open the folder containing your HA install, and locate the config folder.  It will contain a file called (`configuration.yaml`)
2.  If there is not a subfolder in config folder called `custom_components`, create it.
3.  Inside `custom_components` folder, create a new folder named `energytariff`
4.  Download all files from `custom_components/energytariff/` in this repository and put them in `energytariff`-folder
5.  Restart HA

### HACS(recommended)

Go to HACS -> Integrations, click the blue + sign at the bottom right of the screen.
Search for `EnergyTariff` and install it as any other HACS component.
A HA restart is required before configuration for HomeAssistant to pick up the new integration.


## Configuration

**Important!**
After first install of this component, a restart of HomeAssistant is required.
If configuration is added before HA is rebootet after install, configuration validation will fail,
because HA does yet know about the new integration.  This is a known issue, with no easy fix.

Configuration of this sensor is done in yaml.
Minimal example: `configuration.yaml` :

```yaml
sensor:
  - platform: energytariff
    entity_id: "sensor.ams_power_sensor_watt"
    target_energy: 10
```

### Configuration schema

| Name | Type | Default | Since | Description |
|------|------|---------|-------|-------------|
| entity_id | string | **required** | v0.0.1 | entity_id for your AMS meter sensor that provides current power usage.  This sensor is required, and value needs to be in either W or kW. |
| precision | int | 2 | v0.0.1 | Number of decimals to use in rounding.  Defaults to 2, giving all sensors two decimals. |
| target_energy | float | None | v0.0.1 | Target energy consumption in kWh.  See sensor "Available power this hour" for more detailed description. |
| max_power | float | None | v0.0.1 | Max energy(in kWh) reported by "Available power this hour" sensor.See sensor "Available power this hour" for more detailed description. |
| levels | list | None | v0.0.1 | Grid energy levels(primarily for norwegian HA users).  If your energy provider has tariffs based on energy consumption per hour, this list of levels can be utilized.

#### Levels schema

If your electric energy provider uses grid capacity levels, these can be configured by adding this section to configuration.
These tariff levels are used by norwegian grid operators, so this primarily applies to Norwegian HA owners.
Per entry, here are the values needed:

| Name | Type | Default | Since | Description |
|------|------|---------|-------|-------------|
| name | string | **required** | v0.0.1 | Name of grid energy level |
| threshold | float | **required** | v0.0.1 | Energy threshold level, in kWh |
| price | float | **required** | v0.0.1 | Energy level price |

Levels example:

```yaml

levels:
  - name: "Trinn 1: 0-2 kWh"
    threshold: 2
    price: 135
  - name: "Trinn 2: 2-5 kWh"
    threshold: 5
    price: 170
  - name: "Trinn 2: 5-10 kWh"
    threshold: 10
    price: 290
```

For a complete configuration example with all properties, see [full example](examples/full.yaml)

## Sensors

This integration provides the following sensors:

| Name | Unit | Description |
|------|------|-------------|
| [Energy used this hour](#energy-used-this-hour) | kWh | Total amount of energy consumed this hour.  Resets to zero at the start of a new hour. |
| [Energy estimate this hour](#energy-estimate-this-hour) | kWh | Energy estimate this hour.  Based on energy consumption so far + current_power * remaining_seconds |
| [Available power this hour](#available-power-this-hour) | W | How much power that can be used for the remaining part of hour and still remain within threshold limit, either configured in `target_energy` setting or at the configured grid level threshold(`level` threshold). |
| [Average peak hour energy](#average-peak-hour-energy) | kWh | The highest hourly consumption, measured on three different days.  Used to calculate grid energy level.  Resets every month. |

Additionally, if `levels` are configured, the following sensors are added:

| Name | Unit | Description |
|------|------|-------------|
| [Energy level name](#energy-level-name) | string | Name of current energy level |
| [Energy level price](#energy-level-price) | currency | Price of current energy level |
| [Energy level upper threshold](#energy-level-upper-threshold) | kWh | Upper energy threshold of current energy level |

### Energy Used this hour

This sensor displays how much energy that has been consumed so far this hour.  It will reset when a new hour starts.
A typical graph for this sensor looks like this:

![Example energy used](doc/energy_used_this_hour.png)

### Energy estimate this hour

This sensor gives an estimate of how much energy that will be consumed in the current hour.

Given that `EC` is energy consumed, `EF` is current power and `TD` is remaining seconds of hour, calculation is done using this formula:

$$Estimate = EC + {{EF * TD}\over{3600 * 1000}}$$


Output is in kWh.  Sample sensor data:

![Example energy used](doc/energy_estimate_this_hour.png)

### Available power this hour

This sensor shows remaining power you can use this hour without exceeding grid threshold level.  
When sensor value is positive, power usage can be increased by sensor value without exceeding threshold value.
As an example, if value is 1000W, power usage can be increased by 1000W and you will still remain within current grid threshold value.
If sensor value is negative, power usage much be reduced by that amount to remain within threshold value.  So if sensor value is -1500W, you need to reduce power consumption by 1500W to remain withing threshold level.

If `target_energy` setting is configured, this value is used as a threshold.  Otherwise, if `level` setting is configured, the current energy level threshold value is used.  If neither are configured, this sensor is unavailable.

Given that `EC` is energy consumed, `EF` is current power, `TT` is threshold and `TD` is remaining seconds of hour, calculation is done using this formula:

$$Available = {({TT - EC}) * 3600 * 1000 \over TD} - EF$$

If this sensor has a positive value, power usage can be increased without exceeding the threshold.  When the sensor has a negative value, power usage needs to be decreased in order to not exceed threshold.

Sample graph from sensor.  Notice that the sensor does not exceed `max_power` threshold value, which in this case is configured to 15300 W.

![Example energy used](doc/available_effect_this_hour.png)

**max_power parameter**

The last few minutes of an hour `TD` in the formula above will become quite low,
resulting in available power to grow expontentially, and possibly exceeding the total available power that can be used without blowing the main circuit breaker.  It is highly recommended to set this parameter to a sensible value that is below the total power that can be utilized safely.

**target_energy parameter**

Sets the threshold energy value for this sensor to a fixed value.  If not set, threshold value from current grid energy level is used.
As sensor data from three different days are needed in order to calculate grid level properly, it can be useful to set this to a pre-determined level that you do not want to exceed.

## Average peak hour energy
This sensor displays the average of the three hours with highest energy usage, from three different days.
Value is reset when a new month starts.  This sensor is not available if `levels` have not been added to configuration.

**NOTE** Sensor will not work properly until it it has two full days of data + 1 hour from day 3.
For the first day after month start, it will display the highest consumption that is measured for an individual hour.
On day two, it will measure an anverage of highest consumption from day 1 and 2.  On day three the sensor will provide correct values, measuring the average of the three highest hours from three different days.

### Energy level name
This sensor provides the current energy step level for your average energy usage.  If `levels` are not configured, this sensor is not available.

### Energy level upper threshold
This sensor provides the upper threshold value for current energy level.
If `levels` are not configured, this sensor is not available.


### Energy level price
This sensor provides the price for the current energy level.
If `levels` are not configured, this sensor is not available.

## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

[buymecoffee]: https://www.buymeacoffee.com/epaulsen
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=flat
[commits-shield]: https://img.shields.io/github/commit-activity/y/epaulsen/energytariff
[commits]: https://github.com/epaulsen/energytariff/commits/master
[hacs_badge]: https://img.shields.io/badge/HACS-Default-41BDF5.svg
[license-shield]: https://img.shields.io/github/license/epaulsen/energytariff
[analytics_badge]: https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.energytariff.total
