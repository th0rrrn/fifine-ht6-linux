# fifine-ht6-linux

Control tool for the **FIFINE HT6** wireless headset on Linux: battery level,
sound mode, sleep timer and RGB lighting — everything the vendor's Windows
software does over USB, without Windows.

The protocol was recovered by static analysis of the vendor app
(`api_server.exe` + `hid_ota.dll`) and verified on real hardware.

## Supported

| Feature | Status |
|---|---|
| Battery level + charging status | ✅ |
| Sound mode (0/1/2) | ✅ |
| Sleep timer (auto power-off) | ✅ |
| LED modes: always on / cycle / breathing / music rhythm | ✅ |
| LED color (RGB) | ✅ |
| Firmware versions (dongle + headset) | ✅ (read from the state packet) |
| Equalizer | ❌ not in the device — see below |
| Firmware update (OTA) | ❌ not implemented |

Tested on: **VID `3142` / PID `00C3`**, dongle firmware 1.8, headset 4.2.
Other FIFINE models using the same Bolutek/Actions dongle family may work —
`./fifine_ht6.py state` will tell you.

### About the equalizer

The headset has **no DSP of its own**. Everything SoundLink does with EQ,
7.1 surround and spatial audio is a Windows APO driver running on the host,
so there is nothing to port: use PipeWire/EasyEffects instead.
See [docs/AUDIO.md](docs/AUDIO.md) for a working EQ + virtual-surround setup.

## Install

Requires Python 3 and `python-hidapi`:

```bash
# Arch
sudo pacman -S python-hidapi
# Debian/Ubuntu
sudo apt install python3-hid
```

Then:

```bash
git clone https://github.com/th0rrrn/fifine-ht6-linux
cd fifine-ht6-linux
./fifine_ht6.py state
```

No root needed — the device is accessed through `/dev/hidraw*`.

## Usage

```bash
./fifine_ht6.py state                    # battery, mode, LED color, firmware
./fifine_ht6.py mode 1                   # sound mode 0/1/2
./fifine_ht6.py sleep 30                 # auto power-off in minutes (255 = off)
./fifine_ht6.py led breath               # always | cycle | breath | rhythm
./fifine_ht6.py color ff69b4             # LED color (always-on mode)
./fifine_ht6.py color ff69b4 rhythm      # color + mode in one go
./fifine_ht6.py devices                  # list HID interfaces
```

As a library:

```python
import fifine_ht6 as f

dev = f.open_device()
state, _ = f.get_state(dev)
print(state["battery_level"], "%")

f.set_color(dev, 0xFF, 0x69, 0xB4, "rhythm")
dev.close()
```

### Battery for a status bar

`tools/fifine-battery` prints just the percentage, so it drops straight into
waybar, polybar, tmux or a shell prompt:

```bash
fifine-battery          # 80%
fifine-battery --json   # {"connected": true, "battery": 80, ...}
fifine-battery --plain  # 80
```

Returns exit code 1 when the headset is off or the dongle is missing.

## How the protocol works

Short version — the device speaks 64-byte HID reports, report ID `0x55`:

```
55 65 01 00                 read state
55 21 01 <mode>             set sound mode
55 23 01 <minutes>          set sleep timer (255 = off)
55 06 00                    read LED state
```

Writes that change the LED need a **transaction wrapper**
(`55 0C 01 … 55 05 00 55 01 00`) or the dongle silently drops them.
Full details, packet layouts and the reverse-engineering notes:
[docs/PROTOCOL.md](docs/PROTOCOL.md).

`tools/capture.sh` captures USB traffic with `tshark` if you want to extend
support to another model.

## Disclaimer

This is an interoperability project for a device the author owns. The protocol
was derived from observing the vendor's own software; no vendor code is
included. Firmware flashing is intentionally not implemented — get it wrong
and you have a brick.

Not affiliated with FIFINE.

## License

MIT
