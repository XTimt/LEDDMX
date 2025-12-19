"""The LEDDMX integration."""
from __future__ import annotations

import asyncio
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.components import persistent_notification

from .const import DOMAIN
from .device import LEDDMXDevice

_LOGGER = logging.getLogger(__name__)

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
    
    # Forward to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Create success notification
    await _create_success_notification(hass, device)
    
    return True

async def _create_success_notification(hass: HomeAssistant, device):
    """Create success notification."""
    notification_id = f"leddmx_success_{device.address}"
    
    message = (
        f"LEDDMX device **{device.name}** has been successfully configured!\n\n"
        f"Added entities:\n"
        f"- {device.name} (main light)\n"
        f"- {device.name} Microphone (sound-reactive mode)\n\n"
        "You can now control your LEDDMX lights."
    )
    
    persistent_notification.async_create(
        hass,
        message,
        title="✅ LEDDMX Device Added",
        notification_id=notification_id,
    )
    
    # Автоматически удалим через 30 секунд
    async def dismiss_notification():
        await asyncio.sleep(30)
        persistent_notification.async_dismiss(hass, notification_id)
    
    hass.async_create_task(dismiss_notification())

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok and DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok