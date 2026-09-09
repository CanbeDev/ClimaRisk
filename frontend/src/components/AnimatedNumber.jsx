import { useCountUp } from '../lib/useCountUp'

/**
 * Renders `value` through `format`, tweening the number on change.
 * `value` may be a number (animated) or anything else (rendered as-is via
 * `format` if given).
 */
export default function AnimatedNumber({ value, format }) {
  const n = useCountUp(value)
  if (typeof n === 'number' && Number.isFinite(n)) {
    return <>{format ? format(n) : Math.round(n).toLocaleString('en-ZA')}</>
  }
  return <>{format ? format(value) : value}</>
}
