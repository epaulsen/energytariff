"""Constants for grid-cap-watcher."""
# Base component constants
NAME = "Energy tariff"
DOMAIN = "energytariff"
DOMAIN_DATA = f"{DOMAIN}_data"
VERSION = "0.0.3"

ISSUE_URL = "https://github.com/epaulsen/grid-cap-watcher/issues"

# Icons
ICON = "mdi:lightning-bolt"

SENSOR = "sensor"
SWITCH = "switch"
PLATFORMS = [SENSOR]

# Configuration and options
CONF_ENABLED = "enabled"

CONF_EFFECT_ENTITY = "entity_id"
COORDINATOR = "rx_coordinator"


DATA_UPDATED = f"{DOMAIN}_data_updated"
MAX_EFFECT_ALLOWED = "max_power"

GRID_LEVELS = "levels"
LEVEL_NAME = "name"
LEVEL_THRESHOLD = "threshold"
LEVEL_PRICE = "price"
ROUNDING_PRECISION = "precision"
PEAK_HOUR = "peak_hour"
TARGET_ENERGY = "target_energy"

RESET_TOP_THREE = "energytariff_reset_top_three_hours"

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
