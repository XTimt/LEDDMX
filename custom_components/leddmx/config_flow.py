"""Config flow for LEDDMX integration."""
from __future__ import annotations

import re
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth, persistent_notification
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.device_registry import format_mac

from .const import DOMAIN

class LEDDMXConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LEDDMX."""
    
    VERSION = 2
    
    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices = {}

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle discovery via Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        
        # Создаем persistent notification
        await self._create_discovery_notification(discovery_info)
        
        # Store discovery info
        self._discovered_devices[discovery_info.address] = discovery_info
        
        # Show user confirmation dialog
        return await self.async_step_bluetooth_confirm()
    
    async def _create_discovery_notification(self, discovery_info):
        """Create persistent notification for discovered device."""
        notification_id = f"leddmx_discovery_{discovery_info.address}"
        
        message = (
            f"Found LEDDMX device: **{discovery_info.name}**\n\n"
            f"Address: `{discovery_info.address}`\n\n"
            "Go to **Settings → Devices & Services** to add this device."
        )
        
        persistent_notification.async_create(
            self.hass,
            message,
            title="🎉 LEDDMX Device Discovered",
            notification_id=notification_id,
        )

    async def async_step_bluetooth_confirm(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")
        
        # Get the first discovered device
        address = next(iter(self._discovered_devices))
        discovery_info = self._discovered_devices[address]
        
        if user_input is not None:
            # Удаляем уведомление после добавления
            notification_id = f"leddmx_discovery_{discovery_info.address}"
            persistent_notification.async_dismiss(self.hass, notification_id)
            
            # User confirmed, create entry
            return self.async_create_entry(
                title=user_input.get(CONF_NAME, discovery_info.name),
                data={
                    CONF_ADDRESS: discovery_info.address,
                    CONF_NAME: user_input.get(CONF_NAME, discovery_info.name),
                },
            )
        
        # Show confirmation form
        self.context["title_placeholders"] = {
            "name": discovery_info.name,
            "address": discovery_info.address,
        }
        
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": discovery_info.name,
                "address": discovery_info.address,
            },
            data_schema=vol.Schema({
                vol.Optional(CONF_NAME, default=discovery_info.name): str,
            }),
        )

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Handle the initial step (manual setup)."""
        errors = {}
        
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            
            # Validate MAC address format
            try:
                address = format_mac(address)
            except ValueError:
                errors[CONF_ADDRESS] = "invalid_mac_address"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, f"LEDDMX {address[-6:]}"),
                    data={
                        CONF_ADDRESS: address,
                        CONF_NAME: user_input.get(CONF_NAME, f"LEDDMX {address[-6:]}"),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS): str,
                vol.Optional(CONF_NAME, default="LEDDMX Light"): str,
            }),
            errors=errors,
        )