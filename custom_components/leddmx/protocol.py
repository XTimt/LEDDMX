"""BLE frame codecs for the different LEDDMX controller variants.

All LEDDMX controllers share a 9-byte framing on the ffe1 characteristic
(`7B FF <cmd> <b3> <b4> <b5> <b6> <b7> BF`) but the firmware families differ in
opcodes, RGB byte order and whether a login/unlock frame is required.

Rather than sprinkling `if model == ...` over the entity code, each family is a
small codec class. The light entity asks the codec to build frames and never
sees the raw bytes. Adding a new variant = subclass + one line in
:func:`codec_for_name`.
"""
from __future__ import annotations

import datetime


class LedDmxCodec:
    """Shared base codec: 9-byte framing + the original LEDDMX-00 command set.

    Concrete model codecs (:class:`LedDmx00Codec`, :class:`LedDmx03Codec`)
    subclass this and override only what differs.
    """

    name = "leddmx"
    requires_login = False

    # --- 9-byte frame envelope: 7B FF <cmd> <b3..b7> BF (unused args -> 0xFF) ---
    @staticmethod
    def _frame(cmd, b3=0xFF, b4=0xFF, b5=0xFF, b6=0xFF, b7=0xFF):
        return bytes([0x7B, 0xFF, cmd, b3, b4, b5, b6, b7, 0xBF])

    # --- commands ---
    def power(self, on: bool) -> bytes:
        return self._frame(0x04, 0x03 if on else 0x02)

    def color(self, r: int, g: int, b: int) -> bytes:
        # the original LEDDMX-00 protocol expects the channels swapped to G, B, R
        return self._frame(0x07, g, b, r, 0x00)

    def brightness(self, percent: int) -> bytes:
        percent = max(0, min(100, percent))
        return self._frame(0x01, (percent * 32) // 100, percent, 0x00)

    def pattern(self, index: int) -> bytes:
        return self._frame(0x03, index & 0xFF)

    def mic(self, eq_mode: int, on: bool) -> bytes:
        return self._frame(0x0B, (eq_mode & 0xFF) if on else 0x00, 0x00)

    def login_frame(self, now=None):
        """Return the unlock frame, or None if the model needs no login."""
        return None


class LedDmx00Codec(LedDmxCodec):
    """LEDDMX-00 — the original protocol (identical to the shared base)."""

    name = "dmx00"


class LedDmx03Codec(LedDmxCodec):
    """LEDDMX-03 dialect — verified against an HCI snoop of the vendor app.

    Differences vs LEDDMX-00: requires a login frame, different power opcodes,
    direct R,G,B order, and the mic frame carries a 0x01 flag.
    """

    name = "dmx03"
    requires_login = True

    def power(self, on: bool) -> bytes:
        return self._frame(0x04, 0x01 if on else 0x00)

    def color(self, r: int, g: int, b: int) -> bytes:
        return self._frame(0x07, r, g, b, 0x00)

    def mic(self, eq_mode: int, on: bool) -> bytes:
        return self._frame(0x0B, (eq_mode & 0xFF) if on else 0x00, 0x01 if on else 0x00)

    def login_frame(self, now=None) -> bytes:
        # 2A 02 <pwd:4> <weekday<<5|hour> <minute> AF  (default password A1234567).
        # `now` should be a timezone-aware datetime (HA-configured tz); falls back
        # to the host local time so the codec stays usable standalone.
        if now is None:
            now = datetime.datetime.now()
        b6 = ((now.isoweekday() << 5) | now.hour) & 0xFF
        return bytes([0x2A, 0x02, 0xA1, 0x23, 0x45, 0x67, b6, now.minute & 0xFF, 0xAF])


# Registry of name-substring -> codec, most specific first. Unknown names fall
# back to the LEDDMX-00 codec (the original behaviour).
_CODECS = (
    ("LEDDMX-03", LedDmx03Codec),
    ("LEDDMX-00", LedDmx00Codec),
)


def codec_for_name(name: str | None) -> LedDmxCodec:
    """Pick a codec from the advertised BLE name (defaults to LEDDMX-00)."""
    upper = (name or "").upper()
    for needle, codec_cls in _CODECS:
        if needle in upper:
            return codec_cls()
    return LedDmx00Codec()


def is_leddmx_name(name: str | None) -> bool:
    """True if the name looks like any LEDDMX controller (i.e. detection is meaningful)."""
    return "LEDDMX" in (name or "").upper()
