"""
keyboard.py – Keyboard brightness + RGB color controller for disco.

Writes to two ASUS sysfs interfaces:
  brightness  → /sys/class/leds/asus::kbd_backlight/brightness
  RGB color   → /sys/class/leds/asus::kbd_backlight/kbd_rgb_mode

Both writes are cached; only changes cause actual I/O.
RGB support degrades gracefully if the path is unwritable.
"""

from __future__ import annotations

import logging
import os
from typing import Optional
from pathlib import Path

from config import Config, BRIGHTNESS_PATH, MAX_BRIGHTNESS_PATH, RGB_MODE_PATH

log = logging.getLogger(__name__)


class KeyboardController:
    """
    Thin wrapper around the ASUS sysfs brightness interface.

    Usage::

        kc = KeyboardController(cfg)
        kc.verify()           # call once at startup to check permissions
        kc.set_brightness(2)  # call in the main loop
        kc.restore()          # call on exit to put brightness back
    """

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._path: Path = BRIGHTNESS_PATH
        self._last_written: Optional[int] = None
        self._original_brightness: Optional[int] = None

        # RGB state
        self._last_rgb: Optional[tuple[int, int, int]] = None
        self._rgb_ok: bool = True   # set False after first permanent failure

    # ── Public ────────────────────────────────────────────────────────────────

    def verify(self) -> None:
        """
        Sanity-check the sysfs interface.
        Raises RuntimeError with a helpful message if anything is wrong.
        """
        if not self._path.exists():
            raise RuntimeError(
                f"Keyboard brightness path not found: {self._path}\n"
                "Is the asus-nb-wmi driver loaded?  Try: modprobe asus-nb-wmi"
            )

        if not os.access(self._path, os.W_OK):
            raise RuntimeError(
                f"No write permission for {self._path}.\n"
                "Run disco with sudo, or add a udev rule:\n\n"
                '  SUBSYSTEM=="leds", KERNEL=="asus::kbd_backlight", '
                'RUN+="/bin/chmod a+w /sys/class/leds/asus::kbd_backlight/brightness"\n\n'
                "Save to /etc/udev/rules.d/99-asus-kbd-brightness.rules and reload:\n"
                "  sudo udevadm control --reload-rules && sudo udevadm trigger"
            )

        # Read current brightness so we can restore it on exit.
        try:
            self._original_brightness = int(self._path.read_text().strip())
            log.info(
                "Keyboard brightness sysfs OK (current = %d).",
                self._original_brightness,
            )
        except Exception as exc:
            log.warning("Could not read current brightness: %s", exc)

        # Also log the max brightness for reference.
        try:
            max_b = int(MAX_BRIGHTNESS_PATH.read_text().strip())
            log.info("Max brightness reported by driver: %d", max_b)
            if max_b != self._cfg.brightness_ceiling:
                log.warning(
                    "config.brightness_ceiling (%d) differs from driver max (%d). "
                    "Using config value.",
                    self._cfg.brightness_ceiling,
                    max_b,
                )
        except Exception:
            pass

    def set_brightness(self, level: int) -> None:
        """
        Write *level* to sysfs.

        The value is clamped to [brightness_floor, brightness_ceiling].
        The write is skipped if the value hasn't changed since the last call.
        """
        level = max(self._cfg.brightness_floor, min(self._cfg.brightness_ceiling, level))

        if level == self._last_written:
            return  # nothing to do

        try:
            self._path.write_text(str(level))
            self._last_written = level
            log.debug("Brightness → %d", level)
        except PermissionError:
            log.error(
                "Permission denied writing to %s.  "
                "Is the process still running with the right privileges?",
                self._path,
            )
        except OSError as exc:
            log.error("Failed to write brightness: %s", exc)

    def set_rgb(self, r: int, g: int, b: int) -> None:
        """
        Write an RGB color to the ASUS kbd_rgb_mode sysfs file.

        Format: ``0 0 <r> <g> <b> 0``
          field 1: cmd   = 0 (write)
          field 2: mode  = 0 (static)
          field 3-5: RGB = 0-255 each
          field 6: speed = 0 (unused for static)

        Skips the write if the color hasn't changed or if a previous write
        failed permanently (e.g. no write permission).
        """
        if not self._cfg.color_enabled or not self._rgb_ok:
            return

        if (r, g, b) == self._last_rgb:
            return

        # Quantise to avoid flooding sysfs with tiny hue steps.
        # Only write when at least one channel changes by ≥ 3/255.
        if self._last_rgb is not None:
            lr, lg, lb = self._last_rgb
            if abs(r - lr) < 3 and abs(g - lg) < 3 and abs(b - lb) < 3:
                return

        if not RGB_MODE_PATH.exists():
            log.debug("kbd_rgb_mode not found – color disabled.")
            self._rgb_ok = False
            return

        if not os.access(RGB_MODE_PATH, os.W_OK):
            log.warning(
                "No write permission for %s.\n"
                "To enable color, add the RGB paths to the udev rule and re-trigger:\n"
                "  sudo cp 99-asus-kbd-brightness.rules /etc/udev/rules.d/\n"
                "  sudo udevadm control --reload-rules && sudo udevadm trigger",
                RGB_MODE_PATH,
            )
            self._rgb_ok = False
            return

        try:
            RGB_MODE_PATH.write_text(f"0 0 {r} {g} {b} 0\n")
            self._last_rgb = (r, g, b)
            log.debug("RGB → #%02x%02x%02x", r, g, b)
        except PermissionError:
            log.warning("RGB write permission denied – color disabled for this session.")
            self._rgb_ok = False
        except OSError as exc:
            log.debug("RGB write failed: %s", exc)

    def restore(self) -> None:
        """Restore the original brightness (called on clean exit)."""
        if self._original_brightness is not None:
            log.info("Restoring brightness to %d.", self._original_brightness)
            self.set_brightness(self._original_brightness)
