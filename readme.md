# disco 🎵

**Audio-reactive keyboard backlight for ASUS laptops on Linux.**

disco listens to whatever is playing through your speakers — music, videos, games — and makes your keyboard backlight react to it in real time.

- **Beat mode** — keyboard flashes red on big beats, glows blue and tracks volume between them
- **Loudness mode** — brightness follows the audio level continuously
- Smooth, low CPU usage, auto-starts at boot

> Tested on ASUS TUF F15 with Ubuntu Linux + PipeWire. Should work on any modern ASUS laptop (TUF, ROG, Zenbook) that uses the `asus-nb-wmi` kernel driver (specifically requiring the `/sys/class/leds/asus::kbd_backlight` sysfs path).

---

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/sann2sh/disco/main/install.sh | bash
```

That's it. The keyboard starts reacting to audio immediately and auto-starts on every boot.

---

## Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/sann2sh/disco/main/uninstall.sh | bash
```

---

## Usage

After install, disco runs silently in the background. Manage it with:

```bash
systemctl --user status disco      # check if it's running
systemctl --user stop disco        # stop it
systemctl --user start disco       # start it again
journalctl --user -u disco -f      # view live logs
```

---

## Configuration

Copy the example config and edit it:

```bash
cp ~/.local/lib/disco/config.example.json ~/.local/lib/disco/config.json
```

Then restart the service:

```bash
systemctl --user restart disco
```

Key options in `config.json`:

| Option | Default | Description |
|---|---|---|
| `beat_threshold` | `1.7` | How loud a beat must be to trigger red flash (higher = less sensitive) |
| `beat_decay` | `0.25` | How fast brightness fades after a beat |
| `color_enabled` | `true` | Enable RGB colour control |
| `beat_r/g/b` | `255, 0, 0` | Beat flash colour (red) |
| `rest_r/g/b` | `0, 40, 255` | Ambient colour (blue) |
| `sensitivity` | `1.0` | Overall loudness sensitivity |

---

## Requirements

- ASUS laptop with `asus-nb-wmi` driver
- Ubuntu / Debian Linux (systemd + PipeWire or PulseAudio)
- Python 3.10+

---

## License

MIT
