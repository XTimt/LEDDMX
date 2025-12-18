"""The LEDDMX integration."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN
from .device import LEDDMXDevice

_LOGGER = logging.getLogger(__name__)

# Only light platform
PLATFORMS = ["light"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LEDDMX from a config entry."""
    
    hass.data.setdefault(DOMAIN, {})
    
    # Create device instance
    device = LEDDMXDevice(
        hass=hass,
        config_entry=entry,
        address=entry.data[CONF_ADDRESS],
        name=entry.data.get("name", "LEDDMX Light")
    )
    
    hass.data[DOMAIN][entry.entry_id] = device
    
    # Forward to light platform only
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload light platform
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok and DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok