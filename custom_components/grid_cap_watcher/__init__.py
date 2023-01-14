# from homeassistant.core import HomeAssistant
# from homeassistant.config_entries import ConfigEntry
# from .const import DOMAIN


# async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
#     """Set up platform from a ConfigEntry."""

#     hass.data.setdefault(DOMAIN, {})
#     hass.data[DOMAIN][entry.entry_id] = entry.data

#     # Forward the setup to the sensor platform.
#     await hass.async_create_task(
#         hass.config_entries.async_forward_entry_setup(entry, "sensor")
#     )
#     return True


# async def async_setup(hass: HomeAssistant, config: dict) -> bool:
#     """Set up platform from a dictionary"""
#     hass.data.setdefault(DOMAIN, {})
#     return True
