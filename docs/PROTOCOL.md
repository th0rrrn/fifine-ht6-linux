# FIFINE HT6 — USB protocol

Recovered by static analysis of the vendor's Windows software (SoundLink:
`Flow APO.exe` → `api_server.exe`, a PyInstaller bundle → `hid_ota.dll`) and
verified against real hardware (dongle 1.8, headset 4.2).

Device: `VID 3142` / `PID 00C3`, product string `fifine HT6 wireless`.

## Report layout

The device exposes four HID collections in one interface:

| Usage page | Report ID | Size |
|---|---|---|
| `0xFF90` | `0x55` | 63 bytes in / 63 bytes out |
| `0xFF82` | `0x41` | 63 bytes in / 63 bytes out |
| `0x000C` | `0x06` | consumer control (buttons) |
| `0x000B` | `0x07` | telephony (call buttons) |

Everything in this document goes through **report ID `0x55`**: a 64-byte
report where the first byte is the report ID. With hidapi that means
`dev.write(bytes([0x55, cmd, ...]) + zeros_to_64)` — the first byte is the
report ID, not part of the payload.

`0x41` was never used by the vendor app and is not documented here.

## Commands

| Packet | Meaning |
|---|---|
| `55 65 01 00` | read state packet |
| `55 21 01 <mode>` | set sound mode (0/1/2) |
| `55 23 01 <minutes>` | set sleep timer, `255` = disabled |
| `55 06 00` | read LED state |
| `55 0C 01` / `55 0C 00` | enable / disable the RGB engine |
| `55 0B <0\|1>` | local random mode off/on |

## State packet

Reply to `55 65 01 00`, 64 bytes:

| Index | Field | Notes |
|---|---|---|
| 0 | `0x55` | report ID |
| 1 | `0x65` | command echo |
| 2 | `battery_level` | percent |
| 3 | `battery_status` | valid values 2/3/4 |
| 4 | `sound_mode` | 0/1/2 |
| 5 | `surround_71` | flag |
| 6 | `spatial_sound` | flag |
| 7 | `sleep_time` | `255` = disabled |
| 8 | `sidetone_on` | flag |
| 9 | `sidetone_vol` | level |
| 12 | `dongle_version_major` | 1 |
| 13 | `dongle_version_minor` | 8 → firmware 1.8 |
| 16 | `headset_version_major` | 4 |
| 17 | `headset_version_minor` | 2 → firmware 4.2 |
| 18 | `feature_rgb` | headset has RGB |
| 19 | `feature_rgb_bottom` | second RGB zone (0 on HT6) |
| 20 | `feature_rgb_local_switch` | device supports local random mode |
| 21 | `feature_rgb_bottom_switch` | |

Special statuses:

- byte `0x0A` → headset is powered off / disconnected
- byte `0x1A` → wireless link to the headset lost

The green LED on the dongle is a hardware link indicator: there is no feature
flag and no HID command for it. `55 0C 00` only turns off the headset LEDs.

## LED state

Reply to `55 06 00`:

```
55 06 MM RR GG BB SS 00 …
```

- `MM` — mode: 0 static, 1 cycle, 2 breathing, 3 rhythm, 4 off, 5 local random
- `RR GG BB` — current colour (retained while the engine is off)
- `SS` — interval/speed byte (`0x0A` on the tested unit)

## LED writes: the vendor's engine sequence

Sending a colour packet on its own is accepted by the driver but **silently
dropped by the dongle** — `55 06` keeps reporting the old value, which makes it
look like a wrong packet format.

The vendor app stops the LED engine, configures it and starts it again:

```
55 0C 01                       enable RGB
55 02 00                       stop the LED engine
55 03 MM CC CC II II 00        mode, colour count, interval
55 04 <index> <4×RGB>          colour table, four colours per packet
55 05 00                       save to flash
55 01 00                       start the LED engine
```

`55 0C 00` disables the RGB engine entirely — this is the real "lights off"
command used by the app's toggle. `55 0B 01` selects the local random mode
(mode 5) and `55 0B 00` leaves it.

Mode values: `00` static, `01` cycle, `02` breathing, `03` rhythm, `04` off
(reported after `55 0C 00`), `05` local random.

### Colour table

The LED engine reads colours from the uploaded table, not from a colour
register. The table is a list of RGB triples, sent four at a time:

```
55 04 <index_lo> <index_hi> <v0:3> <v1:3> <v2:3> <v3:3>
```

- **static** — 8 entries; the first is the chosen colour, the rest are black;
- **breathing / rhythm** — 128 entries, a linear fade from the chosen colour
  to black: `v[i] = colour * (1 - i / 128)`;
- **cycle** — 126 entries, a fixed rainbow table built into the vendor app.

`CC CC` in the mode packet is the entry count and `II II` is the animation
interval. This is why changing the colour in the app "just works": it
re-uploads the table every time.

## Not in the device

- **Equalizer / 7.1 / spatial audio** — implemented as a Windows APO driver on
  the host. There is no DSP in the dongle or headset; nothing to port.
- **Firmware update** — `hid_ota.dll` exports `do_upgrade`, `fetch_process`,
  `fetch_status`, `reset`, `setup_config`. Not implemented here on purpose:
  two firmware targets (dongle, headset) and two headset revisions, and a
  failed flash has no recovery path.
- **Dongle LED** — the green LED is a hardware link indicator. It is not
  exposed as an RGB zone and no command affects it.

## Capturing traffic

`tools/capture.sh` starts a `tshark` capture on the right `usbmon` bus.
Change a setting in the vendor app while it runs, then compare:

```bash
tshark -r capture.pcap -Y 'usb.transfer_type==0x01 && usb.endpoint_address.direction==0 && usb.data_len==64' \
  -T fields -e frame.time_relative -e usbhid.data
```
