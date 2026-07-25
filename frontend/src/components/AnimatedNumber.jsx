import { useEffect } from 'react'
import { animate, motion, useMotionValue, useTransform } from 'framer-motion'

/**
 * Counting-up/down number. Animates from the previous value (or `from` on
 * first mount) to `value` whenever `value` changes.
 */
export default function AnimatedNumber({ value, from = null, className = '' }) {
  const mv = useMotionValue(from ?? value)
  const rounded = useTransform(mv, (v) => Math.round(v))

  useEffect(() => {
    const controls = animate(mv, value, { duration: 0.9, ease: 'easeOut' })
    return () => controls.stop()
  }, [value, mv])

  return <motion.span className={className}>{rounded}</motion.span>
}
