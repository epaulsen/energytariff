# """Adds config flow for grid-cap-watcher."""
# from typing import Any
# import voluptuous as vol
# from homeassistant import config_entries
# from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
# from homeassistant.const import CONF_NAME, CONF_UNIQUE_ID
# from homeassistant.helpers import selector
# import homeassistant.helpers.config_validation as cv
# from .const import CONF_EFFECT_ENTITY, DOMAIN, LEVEL_NAME, LEVEL_THRESHOLD, LEVEL_PRICE,

# import logging

# _LOGGER: logging.Logger = logging.getLogger(__package__)

# LEVEL_SCHEMA = vol.Schema(
#     {
#         vol.Required(LEVEL_NAME): cv.string,
#         vol.Required(LEVEL_THRESHOLD): cv.small_float,
#         vol.Required(LEVEL_PRICE): cv.small_float,
#     }
# )

# # Use entityselector, see minmax
# CONFIG_SCHEMA = vol.Schema(
#     {
#         vol.Required(CONF_NAME): selector.TextSelector(),
#         vol.Required(CONF_EFFECT_ENTITY): selector.EntitySelector(
#             selector.EntitySelectorConfig(
#                 domain=[SENSOR_DOMAIN],
#             ),
#         ),
#     }
# )


# class GridCapWatcherFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
#     """Config flow for grid_cap_watcher."""

#     VERSION = 1

#     async def async_step_user(self, user_input: dict[str, Any] | None = None):
#         """Invoked when a user initiates a flow via the user interface."""

#         if user_input is not None:
#             self.data = user_input

#             # Create a unique ID:
#             _unique_id = (
#                 f"GCW_{self.data[CONF_NAME]}_{self.data[CONF_EFFECT_ENTITY]}_".replace(
#                     "sensor.", ""
#                 )
#             )
#             self.data[CONF_UNIQUE_ID] = _unique_id

#             return self.async_create_entry(title=self.data[CONF_NAME], data=self.data)

#         return self.async_show_form(step_id="user", data_schema=CONFIG_SCHEMA)
