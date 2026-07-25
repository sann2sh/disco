"""
processor.py – Signal processing pipeline for disco.

Returns a ProcessorResult containing both a brightness level and an RGB color
so the main loop can drive both sysfs files simultaneously.

Beat-mode pipeline
──────────────────
PCM samples
    → RMS
    → dual-EMA (fast tracks transients, slow tracks ambient level)
    → ratio onset detection  (fast/slow > threshold → beat)
    → cooldown gate          (prevents double-triggers)
    → brightness: spike to 3 on beat, decay toward ambient-tracking floor
    → hue: slow cycle + forward jump on beat
    → HSV → RGB output

Normal-mode pipeline
────────────────────
PCM samples
    → RMS → adaptive peak normalisation → EMA → hysteresis → brightness
    → same hue cycle as beat mode (no jumps)
"""

from __future__ import annotations

import colorsys
import math
import time
from dataclasses import dataclass

import numpy as np

from config import Config


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class ProcessorResult:
    """Output of one call to SignalProcessor.process()."""
    brightness: int
    r: int = 255
    g: int = 255
    b: int = 255


# ── Processor ─────────────────────────────────────────────────────────────────

class SignalProcessor:
    """
    Stateful signal processor.

    Call :meth:`process` with each PCM chunk and receive a
    :class:`ProcessorResult` with the brightness level and RGB color to apply.
    """

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

        # ── Normal-mode state ──────────────────────────────────────────────────
        self._ema: float = 0.0
        self._peak: float = cfg.rms_floor
        self._current_brightness: int = cfg.brightness_floor

        # ── Beat-mode state ────────────────────────────────────────────────────
        # Dual EMA: fast reacts to transients, slow tracks ambient level.
        self._fast_ema: float = 0.0
        self._slow_ema: float = cfg.rms_floor

        # Brightness as a float so we can decay fractionally.
        self._beat_brightness: float = float(cfg.brightness_floor)

        # Cooldown counter (frames): prevents re-triggering immediately after a beat.
        self._cooldown: int = 0

        # ── Color state ────────────────────────────────────────────────────────
        self._hue: float = 0.0        # 0.0 – 1.0 position on color wheel (normal mode)
        self._last_ts: float = time.monotonic()
        self._beat_active: bool = False  # True while a beat flash is showing

    # ── Public ────────────────────────────────────────────────────────────────

    def process(self, chunk: np.ndarray) -> ProcessorResult:
        """
        Process one PCM chunk and return a :class:`ProcessorResult`.

        Parameters
        ----------
        chunk:
            1-D float32 PCM samples in [-1, 1].
        """
        rms = self._compute_rms(chunk)

        if self._cfg.beat_mode:
            brightness = self._process_beat(rms)
            # Two fixed colors: beat color while flashing, rest color otherwise
            cfg = self._cfg
            if self._beat_active:
                r, g, b = cfg.beat_r, cfg.beat_g, cfg.beat_b
            else:
                r, g, b = cfg.rest_r, cfg.rest_g, cfg.rest_b
        else:
            self._advance_hue()  # slow color cycle only in normal mode
            brightness = self._process_normal(rms)
            r, g, b = self._hue_to_rgb(self._hue)

        return ProcessorResult(brightness=brightness, r=r, g=g, b=b)

    # ── Normal mode ───────────────────────────────────────────────────────────

    def _process_normal(self, rms: float) -> int:
        cfg = self._cfg

        # Adaptive peak: decays slowly so the full 0-3 range stays in use.
        decay = 1.0 / (cfg.peak_decay_seconds * cfg.update_rate_hz)
        self._peak = max(
            self._peak * (1.0 - decay) + rms * decay,
            rms,
            cfg.rms_floor,
        )

        normalised = min(rms / self._peak, 1.0) * cfg.sensitivity
        normalised = min(normalised, 1.0)

        α = cfg.ema_alpha
        self._ema = α * normalised + (1.0 - α) * self._ema

        new = self._map_to_brightness(self._ema)
        if new != self._current_brightness:
            self._current_brightness = new
        return self._current_brightness

    def _map_to_brightness(self, value: float) -> int:
        cfg = self._cfg
        lo, hi = cfg.brightness_floor, cfg.brightness_ceiling
        levels = hi - lo + 1

        ideal  = value * (levels - 1) + lo
        target = max(lo, min(hi, int(round(ideal))))

        if target == self._current_brightness:
            return target

        # Hysteresis: require crossing the midpoint by a margin.
        boundary = (self._current_brightness + target) / 2.0
        if abs(ideal - boundary) >= cfg.hysteresis * (levels - 1):
            return target
        return self._current_brightness

    # ── Beat mode ─────────────────────────────────────────────────────────────

    def _process_beat(self, rms: float) -> int:
        cfg = self._cfg

        # ── Dual-EMA ──────────────────────────────────────────────────────────
        # fast_ema (α=0.7): tracks loudness for smooth blue brightness
        # slow_ema (α=0.04): long-running ambient reference
        self._fast_ema = 0.70 * rms + 0.30 * self._fast_ema
        self._slow_ema = 0.04 * rms + 0.96 * self._slow_ema
        self._slow_ema = max(self._slow_ema, cfg.rms_floor)

        # For big-beat detection use RAW rms (not the smoothed EMA) so that
        # a single loud frame is seen at its true amplitude, not dampened.
        raw_ratio   = rms          / self._slow_ema   # spiky – for onset detection
        smooth_ratio = self._fast_ema / self._slow_ema  # smooth – for blue brightness

        # ── Big-beat detection (RED flash) ────────────────────────────────────
        is_big_beat = (raw_ratio > cfg.beat_threshold) and (self._cooldown <= 0)

        # Always tick the cooldown so it expires regardless of which branch runs.
        if not is_big_beat and self._cooldown > 0:
            self._cooldown -= 1

        if is_big_beat:
            # Spike to full brightness, switch to red.
            self._beat_brightness = float(cfg.beat_flash_level)
            self._beat_active = True
            self._cooldown = max(1, int(cfg.update_rate_hz * 0.08))

        elif self._beat_active:
            # Decaying from a red flash.
            self._beat_brightness = max(
                float(cfg.beat_floor_min),
                self._beat_brightness * (1.0 - cfg.beat_decay),
            )
            # Hand back to blue tracking once brightness reaches the floor.
            if self._beat_brightness <= cfg.beat_floor_min + 0.08:
                self._beat_active = False
                self._beat_brightness = float(cfg.beat_floor_min)

        else:
            # ── Dynamic blue brightness (volume tracking) ──────────────────────
            # Map smooth_ratio [1.0 … beat_threshold] → [floor_min … floor_max].
            # smooth_ratio ≈ 1.0  → floor_min (dim blue, ambient / silence)
            # smooth_ratio → beat_threshold → floor_max (bright blue, small beats)
            t = (smooth_ratio - 1.0) / max(cfg.beat_threshold - 1.0, 0.01)
            t = max(0.0, min(1.0, t))
            target = cfg.beat_floor_min + t * (cfg.beat_floor_max - cfg.beat_floor_min)
            # Gentle EMA so the blue level moves smoothly rather than snapping.
            self._beat_brightness = 0.25 * target + 0.75 * self._beat_brightness

        return max(cfg.brightness_floor,
                   min(cfg.brightness_ceiling, int(round(self._beat_brightness))))




    # ── Color ─────────────────────────────────────────────────────────────────

    def _advance_hue(self) -> None:
        """Advance the hue by the configured cycle speed (time-based)."""
        now = time.monotonic()
        dt = now - self._last_ts
        self._last_ts = now
        self._hue = (self._hue + self._cfg.color_cycle_hz * dt) % 1.0

    @staticmethod
    def _hue_to_rgb(hue: float) -> tuple[int, int, int]:
        """Convert a hue (0-1) to full-saturation, full-value RGB (0-255)."""
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        return int(r * 255), int(g * 255), int(b * 255)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_rms(chunk: np.ndarray) -> float:
        if chunk.size == 0:
            return 0.0
        return float(math.sqrt(float(np.mean(chunk.astype(np.float64) ** 2))))
