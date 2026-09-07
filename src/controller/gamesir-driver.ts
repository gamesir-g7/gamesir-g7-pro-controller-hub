// GameSir-G7 Pro Bluetooth report parsing. Layout decoded from the
// test/fixtures/controllers/3537-1022-bluetooth.json doctor capture:
// byte 0 report ID 0x07, bytes 1-4 sticks (LX LY RX RY, 0-255 centre 128),
// byte 5 low nibble d-pad hat (0=N clockwise, 0x0f neutral), byte 6 face/
// shoulder bitmask, byte 7 system bitmask, byte 8 R2 analog, byte 9 L2 analog.

import { normalizeGenericAxis } from './generic-driver.js'
import type { ButtonId, ControllerEvent } from '../types.js'

export const GAMESIR_VID = 0x3537
export const GAMESIR_PIDS = [0x1022] // G7 Pro

const REPORT_ID = 0x07
// The home button arrives on its own consumer-control report: 0x02 <bitmask>.
// Mapped to 'touchpad' — the pad's M button is firmware-consumed (profile
// switching) and never reaches the host, and share sends a keyboard
// PrintScreen report, so home is the only spare host-visible button.
const HOME_REPORT_ID = 0x02
const HOME_BIT = 0x80

const BYTE6_MAP: Array<[number, ButtonId]> = [
  [0x01, 'south'],
  [0x02, 'east'],
  [0x08, 'west'],
  [0x10, 'north'],
  [0x40, 'l1'],
  [0x80, 'r1'],
]

const BYTE7_MAP: Array<[number, ButtonId]> = [
  [0x01, 'l2'],
  [0x02, 'r2'],
  [0x04, 'view'],
  [0x08, 'menu'],
  [0x20, 'l3'],
  [0x40, 'r3'],
]

/**
 * Parse a GameSir-G7 Pro Bluetooth HID report (11 bytes) into ControllerEvents.
 * Reports with an unexpected ID or length are ignored — over USB the pad may
 * speak a different protocol, and this parser only knows the Bluetooth layout.
 */
export function parseGameSirReport(data: Buffer): ControllerEvent[] {
  const events: ControllerEvent[] = []
  if (data[0] === HOME_REPORT_ID && data.length >= 2) {
    return [{ kind: 'button', button: 'touchpad', pressed: (data[1]! & HOME_BIT) !== 0 }]
  }
  if (data.length < 10 || data[0] !== REPORT_ID) return events

  for (const [bit, id] of BYTE6_MAP) {
    events.push({ kind: 'button', button: id, pressed: (data[6]! & bit) !== 0 })
  }
  for (const [bit, id] of BYTE7_MAP) {
    events.push({ kind: 'button', button: id, pressed: (data[7]! & bit) !== 0 })
  }

  // D-pad hat: 0-7 clockwise from north, 0x0f (or anything >7) = released.
  const hat = data[5]! & 0x0f
  events.push({ kind: 'button', button: 'dpad_up', pressed: hat === 7 || hat === 0 || hat === 1 })
  events.push({ kind: 'button', button: 'dpad_right', pressed: hat >= 1 && hat <= 3 })
  events.push({ kind: 'button', button: 'dpad_down', pressed: hat >= 3 && hat <= 5 })
  events.push({ kind: 'button', button: 'dpad_left', pressed: hat >= 5 && hat <= 7 })

  events.push({ kind: 'axis', axis: 'left_x', value: normalizeGenericAxis(data[1]!) })
  events.push({ kind: 'axis', axis: 'left_y', value: normalizeGenericAxis(data[2]!) })
  events.push({ kind: 'axis', axis: 'right_x', value: normalizeGenericAxis(data[3]!) })
  events.push({ kind: 'axis', axis: 'right_y', value: normalizeGenericAxis(data[4]!) })
  events.push({ kind: 'axis', axis: 'r2', value: data[8]! / 255 })
  events.push({ kind: 'axis', axis: 'l2', value: data[9]! / 255 })

  return events
}
