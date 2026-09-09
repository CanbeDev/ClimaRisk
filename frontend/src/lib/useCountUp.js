import { useEffect, useRef, useState } from 'react'

const prefersReducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/**
 * Tween a numeric value toward `target` whenever it changes (easeOutCubic).
 * Non-numbers pass straight through; reduced-motion users get the value with
 * no animation. Returns the current display number.
 */
export function useCountUp(target, duration = 650) {
  const [value, setValue] = useState(target)
  const fromRef = useRef(target)
  const rafRef = useRef(0)

  useEffect(() => {
    if (typeof target !== 'number' || !Number.isFinite(target)) {
      fromRef.current = target
      setValue(target)
      return undefined
    }
    if (prefersReducedMotion() || fromRef.current === target || typeof fromRef.current !== 'number') {
      fromRef.current = target
      setValue(target)
      return undefined
    }

    const from = fromRef.current
    const start = performance.now()
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      setValue(from + (target - from) * eased)
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        fromRef.current = target
      }
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [target, duration])

  return value
}
