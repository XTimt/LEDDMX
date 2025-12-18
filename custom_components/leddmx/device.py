"""Device representation for LEDDMX controllers."""
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

class LEDDMXDevice:
    """Representation of a LEDDMX device."""
    
    def __init__(self, hass, config_entry, address, name):
        """Initialize the device."""
        self.hass = hass
        self.config_entry = config_entry
        self.address = address
        self.name = name
        self.model = self._detect_model(name)
        
    def _detect_model(self, device_name):
        """Detect device model from name."""
        import re
        match = re.search(r'LEDDMX[_-]?(\w+)', device_name.upper())
        if match:
            return f"LEDDMX-{match.group(1)}"
        return "LEDDMX"
    
    @property
    def device_info(self):
        """Return device info for Home Assistant."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.address)},
            name=self.name,
            manufacturer="LEDDMX",
            model=self.model,
            sw_version="1.0",
        )