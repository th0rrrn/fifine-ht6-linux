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
| `55 0C 01` … `55 01 00` | transaction wrapper for LED writes (see below) |

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
| 19 | `feature_dongle_rgb` | dongle has RGB |
| 20 | `feature_rgb_switch` | |
| 21 | `feature_dongle_rgb_switch` | |

Special statuses:

- byte `0x0A` → headset is powered off / disconnected
- byte `0x1A` → wireless link to the headset lost

## LED state

Reply to `55 06 00`:

```
55 06 00 RR GG BB 0A 00 …
```

Bytes 3–5 are the current colour, byte 6 is the animation speed.

## LED writes need a transaction

This is the part that cost the most time. Sending the colour packet on its own
is accepted by the driver but **silently dropped by the dongle** — and
`55 06` keeps reporting the old value, which makes it look like a wrong packet
format.

The vendor app always sends a full sequence:

```
55 0C 01                begin
55 02 00                parameter
55 03 <mode> 00 0A      mode: 00 always / 01 cycle / 02 breath / 03 rhythm
55 04 00 00 RR GG BB    colour
55 04 04 00             clear the rest
55 05 00                parameter
55 01 00                commit
```

For a mode change without colour, the same wrapper without the two `55 04`
packets.

### Colour in animated modes

The colour register (`55 04 00 00 RR GG BB`) only affects **always-on** mode.
`cycle`, `breath` and `rhythm` take colours from a **gradient table**, so it
must be re-uploaded whenever the colour changes. Otherwise the mode applies,
`55 06` reports the new colour, and the LED keeps the old one.

The gradient is 128 RGB triples, uploaded as 32 packets of four values:

```
55 04 <offset> 00 <v0:3> <v1:3> <v2:3> <v3:3>      offset = 0x00 … 0x7C, step 4
```

Values fade linearly from the base colour to black:

```
v[i] = colour * (1 - i / 128)
```

The vendor app uploads this table on every device connect, which is why
changing colour in their UI "just works".

Working order:

1. upload the gradient (32 packets)
2. send the transaction with mode + colour

## Not in the device

- **Equalizer / 7.1 / spatial audio** — implemented as a Windows APO driver on
  the host. There is no DSP in the dongle or headset; nothing to port.
- **Firmware update** — `hid_ota.dll` exports `do_upgrade`, `fetch_process`,
  `fetch_status`, `reset`, `setup_config`. Not implemented here on purpose:
  two firmware targets (dongle, headset) and two headset revisions, and a
  failed flash has no recovery path.

## Capturing traffic

`tools/capture.sh` starts a `tshark` capture on the right `usbmon` bus.
Change a setting in the vendor app while it runs, then compare:

```bash
tshark -r capture.pcap -Y 'usb.transfer_type==0x01 && usb.endpoint_address.direction==0 && usb.data_len==64' \
  -T fields -e frame.time_relative -e usbhid.data
```
