"""Config flow for LEDDMX integration."""
from __future__ import annotations

import re
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
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
        
        # Store discovery info
        self._discovered_devices[discovery_info.address] = discovery_info
        
        # Show user confirmation dialog
        return await self.async_step_bluetooth_confirm()

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
            
            # Улучшенная валидация MAC-адреса
            if not self._is_valid_mac(address):
                errors[CONF_ADDRESS] = "invalid_mac_address"
            else:
                try:
                    # Приводим к стандартному формату
                    address = format_mac(address)
                    await self.async_set_unique_id(address)
                    self._abort_if_unique_id_configured()
                    
                    return self.async_create_entry(
                        title=user_input.get(CONF_NAME, f"LEDDMX {address[-6:]}"),
                        data={
                            CONF_ADDRESS: address,
                            CONF_NAME: user_input.get(CONF_NAME, f"LEDDMX {address[-6:]}"),
                        },
                    )
                except ValueError:
                    errors[CONF_ADDRESS] = "invalid_mac_address"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS): str,
                vol.Optional(CONF_NAME, default="LEDDMX Light"): str,
            }),
            errors=errors,
        )
    
    def _is_valid_mac(self, address: str) -> bool:
        """Validate MAC address format."""
        # Регулярное выражение для MAC-адресов
        mac_patterns = [
            r'^([0-9A-F]{2}[:]){5}([0-9A-F]{2})$',  # AA:BB:CC:DD:EE:FF
            r'^([0-9A-F]{2}[-]){5}([0-9A-F]{2})$',  # AA-BB-CC-DD-EE-FF
            r'^[0-9A-F]{12}$',                      # AABBCCDDEEFF
        ]
        
        for pattern in mac_patterns:
            if re.match(pattern, address, re.IGNORECASE):
                return True
        
        # Также проверяем стандартные форматы
        try:
            format_mac(address)
            return True
        except ValueError:
            return False