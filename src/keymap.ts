// Pure input logic: key repeat. No I/O here — everything is unit-testable.

export const REPEAT_DELAY_MS = 400
export const REPEAT_INTERVAL_MS = 100

/**
 * OS-style key repeat: fire immediately on press, again after REPEAT_DELAY_MS,
 * then every REPEAT_INTERVAL_MS until release. One instance handles all keys.
 */
export class KeyRepeater {
  private timers = new Map<string, ReturnType<typeof setTimeout>>()

  press(key: string, fire: () => void): void {
    this.release(key)
    fire()
    const delay = setTimeout(() => {
      const interval = setInterval(fire, REPEAT_INTERVAL_MS)
      this.timers.set(key, interval as unknown as ReturnType<typeof setTimeout>)
    }, REPEAT_DELAY_MS)
    this.timers.set(key, delay)
  }

  release(key: string): void {
    const timer = this.timers.get(key)
    if (timer) {
      clearTimeout(timer)
      clearInterval(timer as unknown as ReturnType<typeof setInterval>)
      this.timers.delete(key)
    }
  }

  releaseAll(): void {
    for (const key of [...this.timers.keys()]) this.release(key)
  }
}
