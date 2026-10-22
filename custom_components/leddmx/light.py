"""Light platform for LEDDMX controllers."""
from __future__ import annotations

import asyncio
import logging
import re

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.components import bluetooth
from homeassistant.util import dt as dt_util
from bleak import BleakClient
from bleak_retry_connector import establish_connection

from .const import DOMAIN, CHAR_UUID
from .patterns import PATTERNS
from .protocol import codec_for_name, is_leddmx_name

_LOGGER = logging.getLogger(__name__)

MIC_EFFECTS = [f"MODE {i}" for i in range(1, 256)]
MAIN_EFFECTS = [effect for effect in PATTERNS if effect != "Off"]


def _notify_handler(sender, data):
    """Log notifications from the controller (e.g. 2A 05 <level> .. = login status)."""
    try:
        _LOGGER.debug("LEDDMX notify: %s", bytes(data).hex())
    except Exception:  # noqa: BLE001
        pass


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up LEDDMX light entities."""
    device = hass.data[DOMAIN][entry.entry_id]

    main_light = LEDDMXMainLight(hass, device, entry.data)
    mic_light = LEDDMXMicLight(hass, device, entry.data)

    main_light.mic_light = mic_light
    mic_light.main_light = main_light

    async_add_entities([main_light, mic_light])


class _LedDmxBLEMixin:
    """Shared BLE transport: model/codec resolution, connect, login and write.

    Expects the host entity to define ``self.hass``, ``self._address``,
    ``self._ble_client``, ``self._codec`` and ``self._codec_resolved``.
    """

    def _resolve_codec(self):
        """Pick the protocol codec once (cached) from the advertised BLE name."""
        if self._codec_resolved:
            return
        dev = bluetooth.async_ble_device_from_address(
            self.hass, self._address.upper(), connectable=False
        )
        name = dev.name if dev else None
        if is_leddmx_name(name):
            self._codec = codec_for_name(name)
            self._codec_resolved = True
            _LOGGER.debug("LEDDMX %s codec: %s", self._address, self._codec.name)

    async def _ensure_login(self):
        """Send the unlock frame once per connection if the codec requires it.

        Tracked separately from the connection: if the codec was still the
        default one when we first connected (model not yet detected) and later
        resolves to a login-required variant, the unlock frame is sent on the
        next write instead of being lost for the life of the connection.
        """
        if not self._codec.requires_login or self._logged_in:
            return
        try:
            await self._ble_client.start_notify(CHAR_UUID, _notify_handler)
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("notify subscribe failed: %s", e)
        await asyncio.sleep(0.3)
        login = self._codec.login_frame(dt_util.now())
        if login:
            _LOGGER.debug("Sending login frame: %s", login.hex())
            await self._ble_client.write_gatt_char(CHAR_UUID, login, response=False)
            await asyncio.sleep(0.25)
        self._logged_in = True

    async def _drop_client(self):
        """Disconnect and forget the cached client (single-connection device)."""
        if self._ble_client is not None:
            try:
                await self._ble_client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self._ble_client = None
        self._logged_in = False

    async def _write_ble(self, data: bytes):
        """Connect (logging in if the codec requires it) and write one frame."""
        self._resolve_codec()
        _LOGGER.debug("Sending BLE data to %s: %s (%d bytes)",
                      self._address, data.hex(), len(data))

        # Drop a stale/dead cached client so we reconnect instead of writing
        # into a dead link (which silently loses the command).
        if self._ble_client is not None and not self._ble_client.is_connected:
            await self._drop_client()

        device = bluetooth.async_ble_device_from_address(
            self.hass, self._address.upper(), connectable=True
        )
        if not device:
            _LOGGER.error("Device not found: %s", self._address)
            return

        for attempt in (1, 2):
            try:
                if self._ble_client is None:
                    _LOGGER.debug("Establishing new connection to %s", self._address)
                    self._ble_client = await establish_connection(
                        client_class=BleakClient,
                        device=device,
                        name=f"LEDDMX-{self._address[-5:]}",
                        max_attempts=3,
                        use_services_cache=True,
                    )
                    self._logged_in = False

                await self._ensure_login()

                await self._ble_client.write_gatt_char(CHAR_UUID, data, response=False)
                _LOGGER.debug("Successfully sent command to %s", self._address)
                return

            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("Write to %s failed (attempt %d/2): %s",
                                self._address, attempt, e)
                await self._drop_client()  # clean up, then retry once from scratch

        _LOGGER.error("Giving up sending to %s after 2 attempts", self._address)

    async def async_will_remove_from_hass(self):
        """Clean up the BLE connection when the entity is removed."""
        await self._drop_client()


class LEDDMXMainLight(_LedDmxBLEMixin, LightEntity):
    """Main LEDDMX light (manual control)."""

    _attr_should_poll = False
    _attr_assumed_state = True

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
        self._effect = "Solid Color"
        self._last_pattern_index = 0  # 0 = solid colour, >0 = a pattern/animation
        self._ble_client = None
        self._logged_in = False
        self._last_brightness = 255
        self._skip_brightness_update = False
        self._codec = codec_for_name(None)  # default codec until the model is resolved
        self._codec_resolved = False
        self.mic_light = None

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

    async def _set_brightness(self, brightness: int, force_update: bool = False):
        """Set brightness."""
        if self._skip_brightness_update and not force_update:
            _LOGGER.debug("Skipping brightness update (flag set)")
            return

        percent = int((brightness * 100) / 255)
        await self._write_ble(self._codec.brightness(percent))
        self._last_brightness = brightness
        self._brightness = brightness

    async def _set_pattern(self, pattern_index: int, update_effect: bool = True, send_brightness: bool = True):
        """Send pattern command to device."""
        pattern_index = max(1, min(210, pattern_index))
        self._last_pattern_index = pattern_index

        await self._write_ble(self._codec.pattern(pattern_index))

        if send_brightness:
            self._skip_brightness_update = True
            await self._set_brightness(self._brightness, force_update=True)
            self._skip_brightness_update = False

        if update_effect:
            self._effect = PATTERNS[pattern_index] if pattern_index < len(PATTERNS) else f"Pattern {pattern_index}"

    async def _set_color(self, rgb, send_brightness: bool = True):
        """Set solid color."""
        self._color = rgb
        await self._write_ble(self._codec.color(rgb[0], rgb[1], rgb[2]))

        if send_brightness:
            self._skip_brightness_update = True
            await self._set_brightness(self._brightness, force_update=True)
            self._skip_brightness_update = False

        self._effect = "Solid Color"
        self._last_pattern_index = 0

    async def _restore_last_state(self):
        """Re-apply the last visible state after a bare power-on (no colour/effect
        given). Restores the last solid colour, or a pattern only if one was
        actually selected — never falls back to an unexpected animation."""
        if self._last_pattern_index and self._last_pattern_index > 0:
            await self._set_pattern(self._last_pattern_index, update_effect=False, send_brightness=False)
        else:
            await self._set_color(self._color, send_brightness=False)

    async def async_turn_on(self, **kwargs):
        """Turn the light on with selected effect."""
        self._resolve_codec()

        if self.mic_light and self.mic_light.is_on:
            _LOGGER.debug("Microphone is on, turning it off first")
            mic_off = self._codec.mic(0, False)
            await self._write_ble(mic_off)
            await asyncio.sleep(0.1)
            await self._write_ble(mic_off)
            self.mic_light._is_on = False
            self.mic_light.async_write_ha_state()

        was_off = not self._is_on

        if ATTR_EFFECT in kwargs:
            effect = kwargs[ATTR_EFFECT]
            if effect in self.effect_list:
                pattern_index = PATTERNS.index(effect)
            else:
                pattern_index = self._extract_pattern_number(effect)

            if was_off:
                await self._write_ble(self._codec.power(True))

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

        elif ATTR_RGB_COLOR in kwargs:
            rgb = kwargs.get(ATTR_RGB_COLOR, self._color)

            if was_off:
                await self._write_ble(self._codec.power(True))

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

        elif ATTR_BRIGHTNESS in kwargs and ATTR_RGB_COLOR not in kwargs and ATTR_EFFECT not in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]

            if was_off:
                await self._write_ble(self._codec.power(True))
                await self._restore_last_state()

            self._brightness = brightness
            await self._set_brightness(brightness)

            self._is_on = True
            self.async_write_ha_state()
            return

        if was_off:
            await self._write_ble(self._codec.power(True))
            await self._restore_last_state()

        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the light off."""
        self._resolve_codec()
        await self._write_ble(self._codec.power(False))
        self._is_on = False
        self.async_write_ha_state()

    def _extract_pattern_number(self, effect_name: str) -> int:
        """Extract pattern number from string."""
        try:
            numbers = re.findall(r'\d+', effect_name)
            if numbers:
                num = int(numbers[0])
                return max(1, min(210, num))
        except (ValueError, TypeError):
            pass
        return 1


class LEDDMXMicLight(_LedDmxBLEMixin, LightEntity):
    """LEDDMX light in microphone (sound-reactive) mode."""

    _attr_should_poll = False
    _attr_assumed_state = True

    def __init__(self, hass, device, config):
        """Initialize the microphone light."""
        self.hass = hass
        self._device = device
        self._address = config.get(CONF_ADDRESS)
        self._attr_unique_id = f"{self._address}_mic_light"
        self._attr_name = f"{config.get(CONF_NAME)} Microphone"
        self._is_on = False
        self._effect = "MODE 1"
        self._eq_mode = 1
        self._ble_client = None
        self._logged_in = False
        self._codec = codec_for_name(None)
        self._codec_resolved = False
        self.main_light = None

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
        """Return supported color modes - only ON/OFF for microphone mode."""
        return {ColorMode.ONOFF}

    @property
    def color_mode(self):
        """Return the current color mode."""
        return ColorMode.ONOFF

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

    async def async_turn_on(self, **kwargs):
        """Turn the microphone mode on."""
        self._resolve_codec()

        if self.main_light and self.main_light.is_on:
            _LOGGER.debug("Main light is on, turning it off first")
            await self.main_light.async_turn_off()
            await asyncio.sleep(0.2)

        await self._write_ble(self._codec.power(False))
        await asyncio.sleep(0.1)
        await self._write_ble(self._codec.power(True))
        await asyncio.sleep(0.1)

        if ATTR_EFFECT in kwargs:
            effect = kwargs[ATTR_EFFECT]
            try:
                eq_mode = int(effect.split()[1])
                eq_mode = max(1, min(255, eq_mode))
            except (IndexError, ValueError):
                eq_mode = self._eq_mode
                effect = f"MODE {eq_mode}"
        else:
            eq_mode = self._eq_mode
            effect = self._effect

        data = self._codec.mic(eq_mode, True)
        _LOGGER.debug("Sending microphone ON command (eq_mode=%d): %s", eq_mode, data.hex())
        await self._write_ble(data)
        await asyncio.sleep(0.05)
        await self._write_ble(data)

        self._is_on = True
        self._effect = effect
        self._eq_mode = eq_mode
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the microphone mode off."""
        self._resolve_codec()
        mic_off = self._codec.mic(0, False)
        _LOGGER.debug("Sending microphone OFF command: %s", mic_off.hex())
        await self._write_ble(mic_off)
        await asyncio.sleep(0.05)
        await self._write_ble(mic_off)

        await self._write_ble(self._codec.power(False))

        self._is_on = False
        self.async_write_ha_state()
