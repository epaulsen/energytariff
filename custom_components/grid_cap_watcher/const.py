"""Constants for grid-cap-watcher."""
# Base component constants
NAME = "grid-cap-watcher"
DOMAIN = "grid_cap_watcher"
DOMAIN_DATA = f"{DOMAIN}_data"
VERSION = "0.0.1"

ISSUE_URL = "https://github.com/epaulsen/grid-cap-watcher/issues"

# Icons
ICON = "mdi:format-quote-close"

SENSOR = "sensor"
SWITCH = "switch"
PLATFORMS = [SENSOR]

# Configuration and options
CONF_ENABLED = "enabled"

CONF_EFFECT_ENTITY = "entity_id"

DATA_UPDATED = f"{DOMAIN}_data_updated"

GRID_LEVELS = "levels"
LEVEL_NAME = "name"
LEVEL_THRESHOLD = "threshold"
LEVEL_PRICE = "price"

PEAK_HOUR = "peak_hour"

SENSOR_DATA_UPDATED = f"{DOMAIN}_event_sensor_update"
SENSOR_DATA_UPDATED_HOUR_COMPLETE = f"{DOMAIN}_event_sensor_update_hour_complete"
SENSOR_DATA_EFFECT_LEVEL_CHANGED = f"{DOMAIN}_event_sensor_effect_level_changed"
SENSOR_DATA_TOP_THREE_CHANGED = f"{DOMAIN}_event_sensor_top_three_changed"

# Defaults
DEFAULT_NAME = DOMAIN


STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
Version: {VERSION}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""
