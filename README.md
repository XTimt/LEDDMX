# LEDDMX

![LEDDMX Icon](https://github.com/XTimt/LEDDMX/blob/main/icons/icon.png)

LEDDMX is a custom Home Assistant integration for Bluetooth lighting devices compatible with the LED LAMP app, with device names in the format `LED DMX XX-YYYY`.

The integration has been tested with the **LEDDMX-00** device, but according to the available documentation, the same BLE commands should also work with **LEDDMX-03**.

- Official app: https://play.google.com/store/apps/details?id=com.ledlamp&hl=en  
- Tested device: https://aliexpress.ru/item/1005005911540303.html

---

## Installation

### Requirements

- Home Assistant 2023.6+
- A working Bluetooth integration in Home Assistant  
  (Bluetooth adapter must be detected and operational)

---

### Installation via HACS

1. Open **HACS**
2. Click the **three dots** in the top-right corner
3. Select **Custom repositories**
4. Paste the GitHub repository URL
5. Select category **Integration**
6. Click **Add**
7. Install integration and Restart Home Assistant

**Important before restarting:**

- Turn **on** the LEDDMX device
- Fully close the **LED LAMP** app on your phone  
  (a force stop is recommended to avoid BLE conflicts)

---

## Adding the Device

### Automatic discovery

If your device name starts with `LEDDMX`, Home Assistant should discover it automatically.

You will see a notification in **Settings → Devices & Services**.

![Auto discovery](https://github.com/user-attachments/assets/56f89e0e-fa16-488d-af4b-f414a97df314)

---

### Manual setup (by MAC address)

If the device is not discovered automatically, you can add it manually using its **MAC address**.

![Manual setup](https://github.com/user-attachments/assets/fb8ad70f-4fc3-460a-a9d9-25113f526e81)

---

## Features

![Features](https://github.com/user-attachments/assets/2f1161e8-4349-4459-bb3e-74cd1c14abc8)

- Turn device on/off  
  (after restarting Home Assistant, the initial connection may take some time)
- Set lighting effects (all effects available in the official app)
- Adjust brightness

---

## Known Limitations

- Only one BLE client can control the device at a time  
  (make sure the mobile app is not running)
- The first connection after a Home Assistant restart may be slow

---

## Disclaimer

This integration is not affiliated with the LEDDMX device manufacturer or the LED LAMP application.
