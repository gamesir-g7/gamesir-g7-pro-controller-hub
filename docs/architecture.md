# Prototype architecture

OpenPad Hub separates hardware-specific protocol work from the Qt interface so
that observations can be tested without connecting a controller.

```text
Qt Quick/QML UI
      |
HubViewModel (Qt properties, workers and timers)
      |
DeviceManager -> ControllerDriver
      |                |
standard Linux     Cyclone2Driver
evdev / UPower     hidraw protocol
      |
domain snapshots -> history / diagnostics / lighting safety
```

## Domain boundary

`ControllerSnapshot`, `InputSnapshot` and `DriverCapabilities` contain the state
presented to the interface. Unknown hardware values remain absent instead of
being inferred.

## Driver boundary

`ControllerDriver` exposes probing, snapshots, inputs, settings and explicitly
capability-gated writes. The UI does not know report layouts or device paths.

The Cyclone 2 driver combines standard Linux interfaces with independently
documented `hidraw` reports. Product-specific writes stay inside that driver.

## Threading

Hardware polling and lighting transactions run outside the UI thread. Input
events use a fast timer while visible; slower background refreshes reduce idle
work. QML receives immutable values through Qt properties and signals.

## Persistent data

- Preferences: XDG Config Home.
- Battery history and private lighting state: XDG Data Home.
- No project data is sent over the network.
- USB captures are stored privately and excluded from version control.

## Write safety

A lighting transaction accepts only a built-in, validated four-zone profile. It
requires a private checkpoint and verified telemetry mode, sends only known zone
registers, then requires three identical read-back samples. Failure triggers a
single recovery to the last verified OpenPad profile and locks further writes if
recovery cannot be confirmed.
