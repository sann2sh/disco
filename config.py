"""
config.py – Configuration for the disco keyboard backlight daemon.

All tuneable parameters live here. Edit this file or pass a path to a
JSON/TOML config on the CLI to override defaults at runtime.
"""

from dataclasses import dataclass, field
from pathlib import Path
import json


# ──────────────────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────────────────

BRIGHTNESS_PATH = Path("/sys/class/leds/asus::kbd_backlight/brightness")
MAX_BRIGHTNESS_PATH = Path("/sys/class/leds/asus::kbd_backlight/max_brightness")
RGB_MODE_PATH = Path("/sys/class/leds/asus::kbd_backlight/kbd_rgb_mode")
RGB_STATE_PATH = Path("/sys/class/leds/asus::kbd_backlight/kbd_rgb_state")


# ──────────────────────────────────────────────────────────────────────────────
# Config dataclass
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Config:
    # ── Capture ────────────────────────────────────────────────────────────────
    # Name of the audio source.  None = auto-detect default output monitor.
    audio_source: str | None = "Monitor of Built-in Audio Analog Stereo"

    # Samples to collect per update cycle (chunk size).
    # Lower = more responsive, higher = smoother / cheaper on CPU at >1 kHz.
    chunk_size: int = 512

    # ── Update Rate ────────────────────────────────────────────────────────────
    # Target Hz for the brightness update loop (30-60 is recommended).
    update_rate_hz: float = 45.0

    # ── Signal Processing ─────────────────────────────────────────────────────
    # EMA smoothing factor α ∈ (0, 1].
    #   Higher → faster response but more flicker.
    #   Lower  → smoother but slower to react.
    ema_alpha: float = 0.15

    # Hysteresis margin (in normalised loudness units, 0-1).
    # The smoothed signal must cross a brightness boundary by this much before
    # the brightness actually changes.
    hysteresis: float = 0.04

    # ── Dynamic Range ─────────────────────────────────────────────────────────
    # Window (seconds) used for the adaptive peak tracker.
    # Longer = more stable normalisation against momentary peaks.
    peak_decay_seconds: float = 8.0

    # Minimum RMS floor – prevents division-by-zero in silence and stops the
    # display going haywire during very quiet passages.
    rms_floor: float = 1e-4

    # ── Brightness ────────────────────────────────────────────────────────────
    # Minimum and maximum brightness levels written to sysfs (inclusive).
    brightness_floor: int = 0
    brightness_ceiling: int = 3   # max_brightness on ASUS TUF F15

    # Sensitivity multiplier applied before mapping.
    # 1.0 = default. Increase to react to quieter audio, decrease to require louder.
    sensitivity: float = 1.0

    # ── Beat Mode ─────────────────────────────────────────────────────────────
    # Enable beat/transient detection instead of absolute loudness tracking.
    beat_mode: bool = False

    # Ratio of fast EMA to slow EMA required to trigger a RED big-beat flash.
    # Small volume increases (ratio 1.0 – this value) drive the blue brightness.
    # Lower = more red flashes.  Range: 1.5 – 3.0.
    beat_threshold: float = 1.7

    # Brightness level to flash to on beat detection.
    beat_flash_level: int = 3

    # Decay speed: higher = faster snap back to rest after a beat.
    # 0.25 → ~4 frames (90 ms) to return to floor.  0.07 = slow fade.
    beat_decay: float = 0.25

    # Brightness and color when a beat is detected.
    beat_r: int = 255
    beat_g: int = 0
    beat_b: int = 0

    # Brightness and color between beats (always-on glow).
    # beat_floor_min: dim blue when silent/ambient.
    # beat_floor_max: bright blue at the loudest non-red level.
    beat_floor_min: int = 0
    beat_floor_max: int = 3
    rest_r: int = 0
    rest_g: int = 40
    rest_b: int = 255


    # ── Color (normal / hue-cycle mode) ───────────────────────────────────────
    # Enable RGB color output via kbd_rgb_mode (requires udev rule or root).
    color_enabled: bool = True

    # How fast the hue cycles in normal (loudness) mode – full rainbow per second.
    # 0.05 = one full cycle every 20 s.  Not used in beat mode.
    color_cycle_hz: float = 0.05

    # How far to jump the hue forward on each beat (only in normal mode).
    beat_hue_jump: float = 0.12

    # ── Misc ──────────────────────────────────────────────────────────────────
    # Verbosity: 0 = silent (errors only), 1 = info, 2 = debug.
    verbosity: int = 1


def load_config(path: Path | None = None) -> Config:
    """Return a Config, optionally overriding defaults from a JSON file."""
    cfg = Config()
    if path is None:
        return cfg
    try:
        data = json.loads(path.read_text())
        for key, value in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
            else:
                raise ValueError(f"Unknown config key: {key!r}")
    except Exception as exc:
        raise RuntimeError(f"Failed to load config from {path}: {exc}") from exc
    return cfg
