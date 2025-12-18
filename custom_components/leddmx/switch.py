"""Switch platform for LEDDMX microphone."""
import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from .const import DOMAIN, CHAR_UUID
from homeassistant.components import bluetooth
from bleak import BleakClient
from bleak_retry_connector import establish_connection, BleakError

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up LEDDMX switch entities."""
    device = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LEDDMXMicSwitch(hass, device, entry.data)])

class LEDDMXMicSwitch(SwitchEntity):
    """Representation of a LEDDMX microphone switch."""
    
    def __init__(self, hass, device, config):
        """Initialize the switch."""
        self.hass = hass
        self._device = device
        self._address = config.get(CONF_ADDRESS)
        self._attr_unique_id = f"{self._address}_mic"
        self._attr_name = "Microphone"
        self._is_on = False  # Default: microphone off
        self._eq_mode = 1    # Default EQ mode when on (Bass Mode)
        self._ble_client = None
        
        # Device info
        self._attr_device_info = device.device_info
        self._attr_has_entity_name = True

    @property
    def unique_id(self):
        """Return unique ID."""
        return self._attr_unique_id

    @property
    def name(self):
        """Return the name of the switch."""
        return "Microphone"

    @property
    def is_on(self):
        """Return true if microphone is on."""
        return self._is_on

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        return {
            "eq_mode": self._eq_mode,
            "eq_mode_name": self._get_eq_mode_name(),
        }
    
    def _get_eq_mode_name(self):
        """Get human readable EQ mode name."""
        if not self._is_on or self._eq_mode == 0:
            return "Microphone Off"
        
        # Map eq_mode values to names
        eq_modes = {
            1: "Bass Mode",
            2: "Mid Frequencies",
            3: "Treble Mode",
            4: "Auto Mode",
            10: "Low Sensitivity",
            50: "Medium Sensitivity",
            100: "High Sensitivity",
            150: "Dynamic Mode",
            255: "Maximum Sensitivity",
        }
        
        # Try exact match
        if self._eq_mode in eq_modes:
            return eq_modes[self._eq_mode]
        
        # Range matching
        if 5 <= self._eq_mode <= 9:
            return f"Sensitivity {self._eq_mode-4}"
        elif 11 <= self._eq_mode <= 49:
            return "Low-Mid Sensitivity"
        elif 51 <= self._eq_mode <= 99:
            return "Medium-High Sensitivity"
        elif 101 <= self._eq_mode <= 149:
            return "High Sensitivity"
        elif 151 <= self._eq_mode <= 254:
            return "Dynamic Mode"
        
        return f"Mode {self._eq_mode}"

    async def _write_ble(self, data: bytes):
        """Send data to BLE device."""
        _LOGGER.debug("Sending mic command to %s: %s", self._address, data.hex())
        
        device = bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if not device:
            _LOGGER.warning("Device not found: %s", self._address)
            return
        
        try:
            if self._ble_client is None:
                self._ble_client = await establish_connection(
                    client_class=BleakClient,
                    device=device,
                    name=f"LEDDMX-{self._address[-5:]}",
                    max_attempts=3,
                    use_services_cache=True
                )
            
            await self._ble_client.write_gatt_char(CHAR_UUID, data, response=False)
            
        except BleakError as e:
            _LOGGER.error("Failed to connect or write to device %s: %s", 
                         self._address, str(e))
            self._ble_client = None

    async def async_turn_on(self, **kwargs):
        """Turn the microphone on with optional eq_mode."""
        _LOGGER.debug("Turning microphone ON with kwargs: %s", kwargs)
        
        # Get eq_mode from kwargs or use current
        eq_mode = kwargs.get("eq_mode", self._eq_mode)
        eq_mode = max(1, min(255, eq_mode))  # 1-255
        
        _LOGGER.debug("Setting EQ mode to: %s", eq_mode)
        
        data = bytes([
            0x7B, 0xFF, 0x0B,
            eq_mode,
            0x00, 0xFF, 0xFF, 0xBF
        ])
        
        await self._write_ble(data)
        self._is_on = True
        self._eq_mode = eq_mode
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the microphone off."""
        _LOGGER.debug("Turning microphone OFF")
        
        data = bytes([
            0x7B, 0xFF, 0x0B,
            0x00,
            0x00, 0xFF, 0xFF, 0xBF
        ])
        
        await self._write_ble(data)
        self._is_on = False
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        """Clean up when entity is removed."""
        if self._ble_client:
            await self._ble_client.disconnect()
            self._ble_client = None