"""
audio.py – Audio capture module for disco.

Captures the default PipeWire/PulseAudio output monitor (loopback) and
feeds PCM chunks to the signal processor via a thread-safe queue.

Requires: soundcard  (pip install soundcard)
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

import numpy as np

from config import Config

log = logging.getLogger(__name__)


class AudioCapture:
    """
    Background thread that reads from the system loopback (speaker monitor)
    and pushes numpy float32 arrays into *out_queue*.

    The capture loop is designed to be extremely lightweight:
    - It reads fixed-size chunks (config.chunk_size samples).
    - It runs in a daemon thread so it is automatically cleaned up on exit.
    - On failure it backs off and retries, so the daemon survives temporary
      audio device changes (e.g. headphones plugged in).
    """

    def __init__(self, cfg: Config, out_queue: queue.Queue):
        self._cfg = cfg
        self._q = out_queue
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the capture thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="audio-capture",
            daemon=True,
        )
        self._thread.start()
        log.info("Audio capture thread started.")

    def stop(self) -> None:
        """Signal the capture thread to stop and wait for it to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        log.info("Audio capture thread stopped.")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        """Main capture loop – runs in a background daemon thread."""
        import soundcard as sc  # imported lazily so the rest works without it

        while not self._stop_event.is_set():
            try:
                source = self._get_loopback(sc)
                if source is None:
                    log.error(
                        "No loopback / monitor source found.  "
                        "Retrying in 5 s…"
                    )
                    time.sleep(5)
                    continue

                log.info("Capturing from: %s", source.name)

                with source.recorder(
                    samplerate=44100,
                    channels=1,
                    blocksize=self._cfg.chunk_size,
                ) as mic:
                    while not self._stop_event.is_set():
                        data = mic.record(numframes=self._cfg.chunk_size)
                        # data shape: (frames, channels) – take channel 0
                        chunk = data[:, 0].astype(np.float32)
                        try:
                            self._q.put_nowait(chunk)
                        except queue.Full:
                            # Drop oldest sample to avoid queue growing unbounded
                            try:
                                self._q.get_nowait()
                            except queue.Empty:
                                pass
                            self._q.put_nowait(chunk)

            except Exception as exc:  # pylint: disable=broad-except
                log.warning("Audio capture error: %s  – retrying in 2 s…", exc)
                time.sleep(2)

    def _get_loopback(self, sc) -> Optional[object]:
        """
        Return the best available loopback / monitor source.

        Priority:
        1. User-specified source name (config.audio_source).
        2. Default speaker's loopback if soundcard supports it.
        3. First microphone-style device whose name contains 'monitor'.
        """
        cfg_source = self._cfg.audio_source

        # ── User-specified ────────────────────────────────────────────────────
        if cfg_source:
            try:
                return sc.get_microphone(cfg_source, include_loopback=True)
            except Exception as exc:
                log.warning("Could not open user-specified source %r: %s", cfg_source, exc)

        # ── Default speaker loopback ──────────────────────────────────────────
        try:
            spk = sc.default_speaker()
            return sc.get_microphone(spk.id, include_loopback=True)
        except Exception:
            pass

        # ── Fallback: any monitor device ──────────────────────────────────────
        try:
            mics = sc.all_microphones(include_loopback=True)
            for m in mics:
                if "monitor" in m.name.lower():
                    return m
        except Exception:
            pass

        return None
