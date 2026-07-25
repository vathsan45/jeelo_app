import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { api } from '../api.js'
import AnimatedNumber from '../components/AnimatedNumber.jsx'
import DiagnosePanel from '../components/DiagnosePanel.jsx'

export default function PlacementSummary() {
  const { sessionId } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.placementSummary(sessionId).then(setData).catch((e) => setError(e.message))
  }, [sessionId])

  if (error) return <p className="mt-24 text-center text-red-400">{error}</p>
  if (!data) return <p className="mt-24 text-center text-zinc-500">Loading…</p>

  return (
    <div className="mt-12 text-center">
      <h1 className="text-2xl font-bold mb-1">Placement complete</h1>
      <p className="text-zinc-400 mb-8">
        {data.correct_count} / {data.questions_answered} correct
      </p>

      <div className="mb-10">
        <p className="text-zinc-500 text-sm uppercase tracking-wide">Your rating</p>
        <p className="text-6xl font-mono font-bold text-violet-400 my-2">
          <AnimatedNumber value={Math.round(data.theta_overall)} from={1200} />
        </p>
        <p className="text-zinc-500">confidence ±{Math.round(data.rd_overall)}</p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-10 text-left">
        {Object.entries(data.per_topic).map(([topic, r], i) => (
          <motion.div
            key={topic}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 + i * 0.1 }}
            className="bg-zinc-900 border border-zinc-800 rounded p-3"
          >
            <p className="text-xs text-zinc-500 mb-1">{topic}</p>
            <p className="font-mono text-lg">{Math.round(r.theta_effective)}</p>
            <p className="text-xs text-zinc-600">{r.attempts_count} attempts</p>
          </motion.div>
        ))}
      </div>

      <DiagnosePanel sessionId={sessionId} />

      <Link
        to="/"
        className="inline-block bg-violet-600 hover:bg-violet-500 rounded px-6 py-2 font-semibold"
      >
        Continue
      </Link>
    </div>
  )
}
