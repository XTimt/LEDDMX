"""Light platform for LEDDMX controllers."""
import asyncio
import logging
import re

from homeassistant.components.light import (
    ATTR_BRIGHTNESS, 
    ATTR_EFFECT, 
    ATTR_RGB_COLOR, 
    ColorMode, 
    LightEntity, 
    LightEntityFeature
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.components import bluetooth
from bleak import BleakClient
from bleak_retry_connector import establish_connection, BleakError

from .const import DOMAIN, CHAR_UUID
from .patterns import PATTERNS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up LEDDMX light entities."""
    # Get device instance
    device = hass.data[DOMAIN][entry.entry_id]
    
    # Create light entity
    light = LEDDMXLight(hass, device, entry.data)
    async_add_entities([light])


class LEDDMXLight(LightEntity):
    """Representation of a LEDDMX light."""
    
    def __init__(self, hass, device, config):
        """Initialize the light."""
        self.hass = hass
        self._device = device
        self._name = config.get(CONF_NAME)
        self._address = config.get(CONF_ADDRESS)
        self._attr_unique_id = f"{self._address}_light"
        self._is_on = False
        self._color = (255, 255, 255)
        self._brightness = 255
        self._effect = "Off"
        self._last_pattern_index = 0
        self._ble_client = None
        self._last_brightness = 255
        self._skip_brightness_update = False

    @property
    def name(self):
        """Return the name of the light."""
        return self._name

    @property
    def unique_id(self):
        """Return the unique ID of the light."""
        return self._attr_unique_id

    @property
    def device_info(self):
        """Return device info."""
        return self._device.device_info

    @property
    def is_on(self):
        """Return true if light is on."""
        return self._is_on

    @property
    def supported_color_modes(self):
        """Flag supported color modes."""
        return {ColorMode.RGB}

    @property
    def color_mode(self):
        """Return the color mode."""
        return ColorMode.RGB

    @property
    def rgb_color(self):
        """Return the rgb color."""
        return self._color

    @property
    def brightness(self):
        """Return the brightness."""
        return self._brightness

    @property
    def effect_list(self):
        """Return the list of available effects."""
        return PATTERNS

    @property
    def effect(self):
        """Return the current effect."""
        return self._effect

    @property
    def supported_features(self):
        """Flag supported features."""
        return LightEntityFeature.EFFECT

    async def _write_ble(self, data: bytes):
        """Send data to BLE device with reliable connection."""
        _LOGGER.debug("Sending BLE data to %s: %s", self._address, data.hex())
        
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

    async def _set_brightness(self, brightness: int, force_update: bool = False):
        """Set brightness."""
        if self._skip_brightness_update and not force_update:
            _LOGGER.debug("Skipping brightness update (flag set)")
            return
            
        brightness_percent = int((brightness * 100) / 255)
        adjusted_percentage = (brightness_percent * 32) // 100
        
        data = bytes([
            0x7B, 0xFF, 0x01,
            adjusted_percentage,
            brightness_percent,
            0x00, 0xFF, 0xFF, 0xBF
        ])
        
        await self._write_ble(data)
        self._last_brightness = brightness
        self._brightness = brightness

    async def _set_pattern(self, pattern_index: int, update_effect: bool = True, send_brightness: bool = True):
        """Send pattern command to device."""
        pattern_index = max(0, min(210, pattern_index))
        self._last_pattern_index = pattern_index
        
        data = bytes([
            0x7B, 0xFF, 0x03, pattern_index,
            0xFF, 0xFF, 0xFF, 0xFF, 0xBF
        ])
        
        await self._write_ble(data)
        
        if send_brightness:
            self._skip_brightness_update = True
            await self._set_brightness(self._brightness, force_update=True)
            self._skip_brightness_update = False
        
        if update_effect:
            self._effect = PATTERNS[pattern_index] if pattern_index < len(PATTERNS) else f"Pattern {pattern_index}"

    async def _set_color(self, rgb, send_brightness: bool = True):
        """Set solid color."""
        self._color = rgb
        r, g, b = rgb[1], rgb[2], rgb[0]  # G, B, R
        
        data = bytes([
            0x7B, 0xFF, 0x07,
            r, g, b,
            0x00, 0xFF, 0xBF
        ])
        
        await self._write_ble(data)
        
        if send_brightness:
            self._skip_brightness_update = True
            await self._set_brightness(self._brightness, force_update=True)
            self._skip_brightness_update = False
        
        self._effect = "Off"
        self._last_pattern_index = 0

    async def async_turn_on(self, **kwargs):
        """Turn the light on with optional color, brightness or effect."""
        was_off = not self._is_on
        
        # Effect
        if ATTR_EFFECT in kwargs:
            effect = kwargs[ATTR_EFFECT]
            
            if effect in PATTERNS:
                pattern_index = PATTERNS.index(effect)
            else:
                pattern_index = self._extract_pattern_number(effect)
            
            if was_off:
                await self._write_ble(bytes.fromhex("7B040401FFFFFFFFBF"))
            
            await self._set_pattern(pattern_index, send_brightness=False)
            
            if ATTR_BRIGHTNESS in kwargs:
                brightness = kwargs[ATTR_BRIGHTNESS]
                self._brightness = brightness
                await self._set_brightness(brightness)
            elif was_off and self._brightness != 255:
                await self._set_brightness(self._brightness)
            
            self._is_on = True
            self.async_write_ha_state()
            return
        
        # Color
        elif ATTR_RGB_COLOR in kwargs:
            rgb = kwargs.get(ATTR_RGB_COLOR, self._color)
            
            if was_off:
                await self._write_ble(bytes.fromhex("7B040401FFFFFFFFBF"))
            
            await self._set_color(rgb, send_brightness=False)
            
            if ATTR_BRIGHTNESS in kwargs:
                brightness = kwargs[ATTR_BRIGHTNESS]
                self._brightness = brightness
                await self._set_brightness(brightness)
            elif was_off and self._brightness != 255:
                await self._set_brightness(self._brightness)
            
            self._is_on = True
            self.async_write_ha_state()
            return
        
        # Brightness only
        elif ATTR_BRIGHTNESS in kwargs and ATTR_RGB_COLOR not in kwargs and ATTR_EFFECT not in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
            
            if was_off:
                await self._write_ble(bytes.fromhex("7B040401FFFFFFFFBF"))
            
            self._brightness = brightness
            await self._set_brightness(brightness)
            
            if self._effect != "Off" and self._last_pattern_index > 0:
                await self._set_pattern(self._last_pattern_index, update_effect=False, send_brightness=False)
            
            self._is_on = True
            self.async_write_ha_state()
            return
        
        # Simple turn on
        await self._write_ble(bytes.fromhex("7B040401FFFFFFFFBF"))
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the light off."""
        data = bytes.fromhex("7B040400FFFFFFFFBF")
        await self._write_ble(data)
        self._is_on = False
        self.async_write_ha_state()

    def _extract_pattern_number(self, effect_name: str) -> int:
        """Extract pattern number from string."""
        try:
            numbers = re.findall(r'\d+', effect_name)
            if numbers:
                num = int(numbers[0])
                return max(0, min(210, num))
        except:
            pass
        return 0

    async def async_will_remove_from_hass(self):
        """Clean up when entity is removed."""
        if self._ble_client:
            await self._ble_client.disconnect()
            self._ble_client = None