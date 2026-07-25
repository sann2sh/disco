#!/usr/bin/env python3
"""
disco – Audio-reactive ASUS TUF F15 keyboard backlight daemon.

Usage
─────
  sudo python disco.py                    # run with defaults
  sudo python disco.py --beat             # beat-flash mode
  sudo python disco.py --config cfg.json  # load config from file
  sudo python disco.py --list-sources     # list available audio sources

Key options (also settable in config JSON):
  --sensitivity   Sensitivity multiplier (default 1.0)
  --ema-alpha     EMA smoothing factor   (default 0.15)
  --rate          Update rate in Hz      (default 45)
  --floor         Minimum brightness     (default 0)
  --ceiling       Maximum brightness     (default 3)
  --verbose / -v  Increase log verbosity (repeat for debug)
"""

from __future__ import annotations

import argparse
import logging
import queue
import signal
import sys
import time
from pathlib import Path

from config import Config, load_config
from audio import AudioCapture
from processor import SignalProcessor, ProcessorResult
from keyboard import KeyboardController


# ── Logging ───────────────────────────────────────────────────────────────────

def _setup_logging(verbosity: int) -> None:
    level = {0: logging.ERROR, 1: logging.INFO, 2: logging.DEBUG}.get(verbosity, logging.DEBUG)
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="disco – audio-reactive ASUS TUF keyboard backlight",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    p.add_argument(
        "--config", "-c",
        metavar="FILE",
        type=Path,
        help="JSON config file to load (overrides built-in defaults).",
    )
    p.add_argument(
        "--list-sources",
        action="store_true",
        help="Print available audio sources and exit.",
    )
    p.add_argument(
        "--source", "-s",
        metavar="NAME",
        help="Audio source / monitor name (default: auto-detect).",
    )
    p.add_argument(
        "--beat", "-b",
        action="store_true",
        help="Enable beat-flash mode instead of loudness mode.",
    )
    p.add_argument(
        "--sensitivity",
        type=float,
        metavar="MULT",
        help="Sensitivity multiplier (>1 = react to quieter audio).",
    )
    p.add_argument(
        "--ema-alpha",
        type=float,
        metavar="α",
        help="EMA smoothing factor ∈ (0,1]. Higher = faster.",
    )
    p.add_argument(
        "--rate",
        type=float,
        metavar="HZ",
        help="Target update rate in Hz.",
    )
    p.add_argument(
        "--floor",
        type=int,
        metavar="N",
        help="Minimum brightness level (0–3).",
    )
    p.add_argument(
        "--ceiling",
        type=int,
        metavar="N",
        help="Maximum brightness level (0–3).",
    )
    p.add_argument(
        "--verbose", "-v",
        action="count",
        default=0,
        help="Increase verbosity (-v = info, -vv = debug).",
    )

    return p.parse_args()


# ── Source listing ────────────────────────────────────────────────────────────

def _list_sources() -> None:
    try:
        import soundcard as sc
    except ImportError:
        print("soundcard is not installed.  Run: pip install soundcard")
        sys.exit(1)

    print("\n── Speakers / output devices ──────────────────────────────────────")
    try:
        for spk in sc.all_speakers():
            print(f"  {spk.name}")
    except Exception as exc:
        print(f"  (error: {exc})")

    print("\n── Microphones + loopback monitors ────────────────────────────────")
    try:
        for mic in sc.all_microphones(include_loopback=True):
            print(f"  {mic.name}")
    except Exception as exc:
        print(f"  (error: {exc})")

    print()


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    args = _parse_args()

    # Verbosity: flag overrides config
    verbosity = args.verbose if args.verbose else 1
    _setup_logging(verbosity)

    log = logging.getLogger("disco")

    # ── List sources and exit ─────────────────────────────────────────────────
    if args.list_sources:
        _list_sources()
        return

    # ── Build config ──────────────────────────────────────────────────────────
    cfg = load_config(args.config)

    # CLI flags override config-file values
    if args.source:
        cfg.audio_source = args.source
    if args.beat:
        cfg.beat_mode = True
    if args.sensitivity is not None:
        cfg.sensitivity = args.sensitivity
    if args.ema_alpha is not None:
        cfg.ema_alpha = args.ema_alpha
    if args.rate is not None:
        cfg.update_rate_hz = args.rate
    if args.floor is not None:
        cfg.brightness_floor = args.floor
    if args.ceiling is not None:
        cfg.brightness_ceiling = args.ceiling
    if args.verbose:
        cfg.verbosity = args.verbose

    # ── Check dependencies ────────────────────────────────────────────────────
    try:
        import soundcard  # noqa: F401
    except ImportError:
        log.error(
            "soundcard is not installed.\n"
            "Install it with:  pip install soundcard\n"
            "You may also need:  sudo apt install libpulse-dev"
        )
        sys.exit(1)

    # ── Initialise components ─────────────────────────────────────────────────
    keyboard = KeyboardController(cfg)
    try:
        keyboard.verify()
    except RuntimeError as exc:
        log.error("%s", exc)
        sys.exit(1)

    audio_queue: queue.Queue = queue.Queue(maxsize=8)
    capture = AudioCapture(cfg, audio_queue)
    processor = SignalProcessor(cfg)

    # ── Signal handling ───────────────────────────────────────────────────────
    running = True

    def _shutdown(signum, frame):  # noqa: ANN001
        nonlocal running
        log.info("Received signal %d – shutting down…", signum)
        running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # ── Start ─────────────────────────────────────────────────────────────────
    mode = "beat-flash" if cfg.beat_mode else "loudness"
    log.info(
        "disco starting  [mode=%s  rate=%.0f Hz  α=%.2f  sensitivity=%.2f]",
        mode,
        cfg.update_rate_hz,
        cfg.ema_alpha,
        cfg.sensitivity,
    )

    capture.start()

    interval = 1.0 / cfg.update_rate_hz
    last_tick = time.monotonic()

    try:
        while running:
            now = time.monotonic()
            elapsed = now - last_tick

            if elapsed < interval:
                time.sleep(interval - elapsed)
                continue

            last_tick = time.monotonic()

            # Drain all pending chunks, keep only the most recent
            chunk = None
            while True:
                try:
                    chunk = audio_queue.get_nowait()
                except queue.Empty:
                    break

            if chunk is None:
                # No audio data yet – leave brightness unchanged
                continue

            result = processor.process(chunk)
            keyboard.set_brightness(result.brightness)
            keyboard.set_rgb(result.r, result.g, result.b)

    finally:
        capture.stop()
        keyboard.restore()
        log.info("disco stopped.")


if __name__ == "__main__":
    main()
