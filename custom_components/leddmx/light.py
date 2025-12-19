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

# Создаем эффекты для микрофона (MODE 1 - MODE 255)
MIC_EFFECTS = [f"MODE {i}" for i in range(1, 256)]

# Убираем "Off" из списка эффектов для основного светильника
MAIN_EFFECTS = [effect for effect in PATTERNS if effect != "Off"]

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up LEDDMX light entities."""
    device = hass.data[DOMAIN][entry.entry_id]
    
    # Создаем два светильника
    main_light = LEDDMXMainLight(hass, device, entry.data)
    mic_light = LEDDMXMicLight(hass, device, entry.data)
    
    # Связываем их для координации
    main_light.mic_light = mic_light
    mic_light.main_light = main_light
    
    async_add_entities([main_light, mic_light])


class LEDDMXMainLight(LightEntity):
    """Основной светильник LEDDMX (ручное управление)."""
    
    def __init__(self, hass, device, config):
        """Initialize the main light."""
        self.hass = hass
        self._device = device
        self._name = config.get(CONF_NAME)
        self._address = config.get(CONF_ADDRESS)
        self._attr_unique_id = f"{self._address}_main_light"
        self._is_on = False
        self._color = (255, 255, 255)
        self._brightness = 255
        self._effect = "Forward Dreaming"  # Дефолтный эффект вместо "Off"
        self._last_pattern_index = 1  # Индекс для "Forward Dreaming"
        self._ble_client = None
        self._last_brightness = 255
        self._skip_brightness_update = False
        self.mic_light = None  # Будет установлено после создания

    @property
    def name(self):
        """Return the name of the light."""
        return f"{self._name}"

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
        return MAIN_EFFECTS

    @property
    def effect(self):
        """Return the current effect."""
        return self._effect

    @property
    def supported_features(self):
        """Flag supported features."""
        return LightEntityFeature.EFFECT

    async def _write_ble(self, data: bytes):
        """Send data to BLE device."""
        _LOGGER.debug("Sending BLE data to %s: %s (%d bytes)", 
                     self._address, data.hex(), len(data))
        
        device = bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if not device:
            _LOGGER.error("Device not found: %s", self._address)
            return
        
        try:
            if self._ble_client is None:
                _LOGGER.debug("Establishing new connection to %s", self._address)
                self._ble_client = await establish_connection(
                    client_class=BleakClient,
                    device=device,
                    name=f"LEDDMX-{self._address[-5:]}",
                    max_attempts=3,
                    use_services_cache=True
                )
            
            await self._ble_client.write_gatt_char(CHAR_UUID, data, response=False)
            _LOGGER.debug("Successfully sent command to %s", self._address)
            
        except Exception as e:
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
        pattern_index = max(1, min(210, pattern_index))  # Минимум 1, убираем 0 (Off)
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
        # G, B, R - как указано
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
        
        self._effect = "Solid Color"
        self._last_pattern_index = 0

    async def async_turn_on(self, **kwargs):
        """Turn the light on with selected effect."""
        # Если микрофон включен, сначала выключаем его
        if self.mic_light and self.mic_light.is_on:
            _LOGGER.debug("Microphone is on, turning it off first")
            # Принудительно отправляем команду выключения микрофона
            mic_off_data = bytes([
                0x7B, 0xFF, 0x0B,
                0x00,  # eq_mode = 0 отключает микрофон
                0x00, 0xFF, 0xFF, 0xFF, 0xBF
            ])
            # Отправляем 2 раза для надежности
            await self._write_ble(mic_off_data)
            await asyncio.sleep(0.1)
            await self._write_ble(mic_off_data)
            
            self.mic_light._is_on = False
            self.mic_light.async_write_ha_state()
        
        was_off = not self._is_on
        
        # Если указан эффект, отправляем его
        if ATTR_EFFECT in kwargs:
            effect = kwargs[ATTR_EFFECT]
            
            if effect in self.effect_list:
                pattern_index = PATTERNS.index(effect)
            else:
                pattern_index = self._extract_pattern_number(effect)
            
            # Включаем устройство (правильная команда из Dmx00Data.kt)
            if was_off:
                await self._write_ble(bytes([0x7B, 0xFF, 0x04, 0x03, 0xFF, 0xFF, 0xFF, 0xFF, 0xBF]))
            
            # Устанавливаем эффект
            await self._set_pattern(pattern_index, send_brightness=False)
            
            # Устанавливаем яркость
            if ATTR_BRIGHTNESS in kwargs:
                brightness = kwargs[ATTR_BRIGHTNESS]
                self._brightness = brightness
                await self._set_brightness(brightness)
            elif was_off and self._brightness != 255:
                await self._set_brightness(self._brightness)
            
            self._is_on = True
            self.async_write_ha_state()
            return
        
        # Если указан цвет
        elif ATTR_RGB_COLOR in kwargs:
            rgb = kwargs.get(ATTR_RGB_COLOR, self._color)
            
            # Включаем устройство
            if was_off:
                await self._write_ble(bytes([0x7B, 0xFF, 0x04, 0x03, 0xFF, 0xFF, 0xFF, 0xFF, 0xBF]))
            
            # Устанавливаем цвет
            await self._set_color(rgb, send_brightness=False)
            
            # Устанавливаем яркость
            if ATTR_BRIGHTNESS in kwargs:
                brightness = kwargs[ATTR_BRIGHTNESS]
                self._brightness = brightness
                await self._set_brightness(brightness)
            elif was_off and self._brightness != 255:
                await self._set_brightness(self._brightness)
            
            self._is_on = True
            self.async_write_ha_state()
            return
        
        # Если только яркость
        elif ATTR_BRIGHTNESS in kwargs and ATTR_RGB_COLOR not in kwargs and ATTR_EFFECT not in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
            
            if was_off:
                # Включаем с последним эффектом
                await self._write_ble(bytes([0x7B, 0xFF, 0x04, 0x03, 0xFF, 0xFF, 0xFF, 0xFF, 0xBF]))
                await self._set_pattern(self._last_pattern_index, update_effect=False, send_brightness=False)
            
            self._brightness = brightness
            await self._set_brightness(brightness)
            
            self._is_on = True
            self.async_write_ha_state()
            return
        
        # Простое включение - используем последний эффект
        if was_off:
            await self._write_ble(bytes([0x7B, 0xFF, 0x04, 0x03, 0xFF, 0xFF, 0xFF, 0xFF, 0xBF]))
            await self._set_pattern(self._last_pattern_index, update_effect=False, send_brightness=False)
        
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the light off."""
        # Правильная команда выключения из Dmx00Data.kt
        data = bytes([0x7B, 0xFF, 0x04, 0x02, 0xFF, 0xFF, 0xFF, 0xFF, 0xBF])
        await self._write_ble(data)
        self._is_on = False
        self.async_write_ha_state()

    def _extract_pattern_number(self, effect_name: str) -> int:
        """Extract pattern number from string."""
        try:
            numbers = re.findall(r'\d+', effect_name)
            if numbers:
                num = int(numbers[0])
                return max(1, min(210, num))  # Минимум 1
        except:
            pass
        return 1  # Default to first effect

    async def async_will_remove_from_hass(self):
        """Clean up when entity is removed."""
        if self._ble_client:
            try:
                await self._ble_client.disconnect()
            except:
                pass
            self._ble_client = None


class LEDDMXMicLight(LightEntity):
    """Светильник LEDDMX в режиме микрофона."""
    
    def __init__(self, hass, device, config):
        """Initialize the microphone light."""
        self.hass = hass
        self._device = device
        self._address = config.get(CONF_ADDRESS)
        self._attr_unique_id = f"{self._address}_mic_light"
        self._attr_name = f"{config.get(CONF_NAME)} Microphone"
        self._is_on = False
        self._effect = "MODE 1"  # Дефолтный режим
        self._eq_mode = 1  # Соответствует MODE 1
        self._ble_client = None
        self.main_light = None  # Будет установлено после создания

    @property
    def name(self):
        """Return the name of the light."""
        return f"{self._attr_name}"

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
        """Return true if microphone light is on."""
        return self._is_on

    @property
    def supported_color_modes(self):
        """No color control in microphone mode."""
        return set()

    @property
    def effect_list(self):
        """Return the list of available microphone effects."""
        return MIC_EFFECTS

    @property
    def effect(self):
        """Return the current microphone effect."""
        return self._effect

    @property
    def supported_features(self):
        """Flag supported features."""
        return LightEntityFeature.EFFECT

    async def _write_ble(self, data: bytes):
        """Send data to BLE device."""
        _LOGGER.debug("Sending mic BLE data to %s: %s (%d bytes)", 
                     self._address, data.hex(), len(data))
        
        device = bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if not device:
            _LOGGER.error("Device not found: %s", self._address)
            return
        
        try:
            if self._ble_client is None:
                _LOGGER.debug("Establishing new mic connection to %s", self._address)
                self._ble_client = await establish_connection(
                    client_class=BleakClient,
                    device=device,
                    name=f"LEDDMX-{self._address[-5:]}",
                    max_attempts=3,
                    use_services_cache=True
                )
            
            await self._ble_client.write_gatt_char(CHAR_UUID, data, response=False)
            _LOGGER.debug("Successfully sent mic command to %s", self._address)
            
        except Exception as e:
            _LOGGER.error("Failed to connect or write to device %s: %s", 
                         self._address, str(e))
            self._ble_client = None

    async def async_turn_on(self, **kwargs):
        """Turn the microphone mode on."""
        # Если основной свет включен, сначала выключаем его
        if self.main_light and self.main_light.is_on:
            _LOGGER.debug("Main light is on, turning it off first")
            # Принудительно выключаем основной свет
            await self.main_light.async_turn_off()
            await asyncio.sleep(0.2)  # Даем устройству время на реакцию
        
        # ВАЖНО: Принудительно сбрасываем состояние устройства
        # Отправляем команду выключения
        power_off_data = bytes([0x7B, 0xFF, 0x04, 0x02, 0xFF, 0xFF, 0xFF, 0xFF, 0xBF])
        await self._write_ble(power_off_data)
        await asyncio.sleep(0.1)
        
        # Включаем устройство
        power_on_data = bytes([0x7B, 0xFF, 0x04, 0x03, 0xFF, 0xFF, 0xFF, 0xFF, 0xBF])
        await self._write_ble(power_on_data)
        await asyncio.sleep(0.1)
        
        # Get effect from kwargs or use current
        if ATTR_EFFECT in kwargs:
            effect = kwargs[ATTR_EFFECT]
            
            # Извлекаем номер режима из "MODE X"
            try:
                eq_mode = int(effect.split()[1])
                eq_mode = max(1, min(255, eq_mode))
            except (IndexError, ValueError):
                eq_mode = self._eq_mode
                effect = f"MODE {eq_mode}"
        else:
            eq_mode = self._eq_mode
            effect = self._effect
        
        # ПРАВИЛЬНАЯ команда микрофона: 9 байт согласно Dmx00Data.kt
        # 0x7B, 0xFF, 0x0B, eq_mode, 0x00, 0xFF, 0xFF, 0xFF, 0xBF
        data = bytes([
            0x7B, 0xFF, 0x0B,
            eq_mode,
            0x00, 0xFF, 0xFF, 0xFF, 0xBF
        ])
        
        _LOGGER.debug("Sending microphone ON command (eq_mode=%d): %s", eq_mode, data.hex())
        
        # Отправляем команду микрофона 2 раза для надежности
        await self._write_ble(data)
        await asyncio.sleep(0.05)
        await self._write_ble(data)
        
        self._is_on = True
        self._effect = effect
        self._eq_mode = eq_mode
        
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the microphone mode off."""
        # Согласно Dmx00Data.kt: eq_mode = 0 выключает микрофон
        # 0x7B, 0xFF, 0x0B, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0xBF
        data = bytes([
            0x7B, 0xFF, 0x0B,
            0x00,  # eq_mode = 0 отключает микрофон
            0x00, 0xFF, 0xFF, 0xFF, 0xBF
        ])
        
        _LOGGER.debug("Sending microphone OFF command: %s", data.hex())
        
        # Отправляем команду выключения 2 раза для надежности
        await self._write_ble(data)
        await asyncio.sleep(0.05)
        await self._write_ble(data)
        
        # Также отправляем команду выключения устройства для полного сброса
        power_off_data = bytes([0x7B, 0xFF, 0x04, 0x02, 0xFF, 0xFF, 0xFF, 0xFF, 0xBF])
        await self._write_ble(power_off_data)
        
        self._is_on = False
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        """Clean up when entity is removed."""
        if self._ble_client:
            try:
                await self._ble_client.disconnect()
            except:
                pass
            self._ble_client = None