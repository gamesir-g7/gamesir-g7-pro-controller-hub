# Independent Cyclone 2 protocol notes

Status: experimental observations verified on hardware owned by the project
author. This specification was not extracted from GameSir firmware, DLLs or
source code.

## Observed identities

| Vendor | Product | Observed context |
|---|---|---|
| `3537` | `0575` | USB, configuration/power |
| `3537` | `100b` | 2.4 GHz receiver/XInput |

The OpenPad Hub udev rule is restricted to these two combinations.

A passive observation of `3537:0575` while the controller received USB power
returned a 64-byte `0x12` report without a valid percentage or charging flag.
OpenPad can report the presence of USB power in this mode, but it does not claim
that the battery is charging and does not invent a percentage.

## Battery read on `3537:100b`

1. Open the matching `hidraw` node for non-blocking read/write access.
2. Send the three-byte heartbeat `0f f2 00`.
3. Wait for a 64-byte report with ID `0x12`.
4. Require byte 35 to be `0` or `1` and byte 36 to be in `0..100`.

Confirmed fields:

| Offset | Meaning | Values |
|---:|---|---|
| 0 | Report ID | `0x12` |
| 35 | Charging state | `0` not charging, `1` charging |
| 36 | Battery | percentage `0..100` |
| 37 | Lighting telemetry code | observed `0..255`; not a hardware configuration identifier |
| 38–52 | Live RGB samples | five consecutive `R,G,B` triplets; not directly equal to the four configurable zones |

Truncated reports, other IDs and out-of-range values are discarded. Lighting
fields changed at the same rate as the physical animation and need no additional
request; OpenPad presents them only as telemetry. The heartbeat has no known
persistent setting side effect.

On the tested firmware, code `2` matched an animation alternating left and right
lights. After using `M + left stick`, code `1` matched a full-lighting spectrum
animation. This observation does not prove that every firmware version shares
the same effect table.

## Safely implementing static RGB writes

The observed `3537:100b` HID descriptor declares output report `0x0f` with up to
63 data bytes. This proves that a write channel exists, but the descriptor does
not describe the meaning of its fields. The heartbeat `0f f2 00` is the only
write independently discovered by this project.

In June 2026, the independent GPL-3.0 project
[`cyclone2-linux`](https://github.com/vdemonchy/cyclone2-linux) published
reproducible captures for the LED subsystem. OpenPad uses that public
specification with attribution: 64-byte reports beginning `0f 03 20`, effect
selection at register `0x01`, brightness at `0x04`, and four zones at `0x05`,
`0x08`, `0x0e` and `0x11`. Consecutive writes use a conservative 80 ms gap.

Those public frames alone did not unlock writes. OpenPad additionally required a
private checkpoint, independent read-back and verified recovery.

Hardware test on July 15, 2026, using receiver `3537:100b` and USB
`bcdDevice 1.21`:

- Four zone writes physically applied violet, cyan, mint and lavender.
- The documented enter-static report was accepted as a complete 64-byte write,
  but telemetry remained at code `2` and the alternating animation continued.
- `HIDIOCGOUTPUT` for `0x0f` and `HIDIOCGINPUT` for `0x10`/`0x12` returned
  `EPIPE`; the descriptor declares no Feature reports. This firmware does not
  expose a standard read of configured LED registers.

At that stage, zone writes were only partially confirmed and static mode,
read-back and recovery stayed locked. Later physical tests resolved those three
requirements without sending an unknown mode command.

## Telemetry-based static read-back

A later hardware test identified the observed firmware telemetry table:

- `0`: static;
- `1`: full-zone spectrum;
- `2`: alternating left/right flow.

In mode `0`, samples are stable and map to the physical zones as follows:

| Physical zone | Telemetry sample | Report offset |
|---|---|---:|
| Left | LIVE 2 | 41 |
| Right | LIVE 3 | 44 |
| Logo | LIVE 1 | 38 |
| Center | LIVE 5 | 50 |

LIVE 4 at offset 47 remains black. Each reported channel equals
`floor(configured_channel / 2)`. This mapping was confirmed by applying the
Aurora profile and comparing all four physical lights with five identical
reports.

The official manual describes four physical configurations selected with
`M + right stick up/down`: Default lights one channel indicator, Configuration
1 lights two, Configuration 2 lights three, and Configuration 3 lights all four.
A physical test confirmed that byte 37 does not change while switching these
configurations, so OpenPad does not use it as a slot identifier. The initial
safety procedure reserves Configuration 3 by visual confirmation, leaving the
other configurations as a physical escape path.

OpenPad contains eight original four-zone profiles. They all use static
telemetry mode `0`, so byte 37 correctly remains `0` when switching between
them. Profile identity comes from matching the four returned zone colors, not
from fabricating a telemetry code.

Animated `0x12` triplets are rendered live samples and are never accepted as
configured-state verification. Static changes require three identical reports.
The commissioning test changed Aurora to Deep Ocean and restored Aurora,
verifying both states. If a later operation fails, the engine restores the last
verified profile; if recovery cannot also be confirmed, writes remain locked
and the error is shown.

Observed effects `1` (spectrum) and `2` (side flow) remain read-only. Available
public sequences do not prove selection, configured-state read-back and recovery
on the tested firmware. They can be changed physically with `M + left stick`.

## Research procedure for additional writes

Before another RGB setting can be enabled, independently capture USB traffic
from a legitimate installation of the official application while changing one
variable per capture:

1. Read and preserve the current controller state.
2. Capture off, static red, green and blue separately.
3. Capture minimum/maximum brightness and every animation separately.
4. Compare output reports for command, fields, length and checksum.
5. Repeat each observation in more than one session and identify read-back.
6. Implement encoder, decoder and automated tests using anonymized fixtures.
7. Prove recovery before exposing the control in the normal interface.

Captures must not contain or redistribute manufacturer executables, resources,
firmware or source code.

### OpenPad passive RGB laboratory

The laboratory uses the stable `usbmon` ABI and filters the exact bus and device
address for `3537:100b`. It does not open `hidraw`, send reports or interpret
unknown fields. Captures and manifests are created under
`XDG_DATA_HOME/openpad-hub/rgb-lab` with private permissions.

```bash
python3 openpad_hub.py --rgb-capture idle-baseline --capture-seconds 12
python3 openpad_hub.py --rgb-capture static-red --capture-seconds 12
python3 openpad_hub.py --rgb-compare BASELINE.pcap STATIC-RED.pcap
```

During the second capture, change exactly one setting from a legitimate copy of
the official application. The comparator removes the known heartbeat
`0f f2 00` and lists output reports that become more frequent after the change.
One difference is not a verified protocol: it must reproduce across red, green,
blue, off and multiple brightness levels.

Even with the device filter, captures stay private until identifiers, serial
numbers and environmental data have been reviewed.

## Not yet validated

Signal strength, gyroscope telemetry, brightness, animated-effect selection,
vibration, dead zones and calibration remain unverified or incomplete. Firmware
updates are permanently outside the current scope. A feature must not be
advertised or implemented from conjecture.
