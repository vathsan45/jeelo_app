import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { api } from '../api.js'
import DiagnosePanel from '../components/DiagnosePanel.jsx'

export default function QuizSummary() {
  const { sessionId } = useParams()
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.getReport(sessionId).then(setReport).catch((e) => setError(e.message))
  }, [sessionId])

  if (error) return <p className="mt-24 text-center text-red-400">{error}</p>
  if (!report) return <p className="mt-24 text-center text-zinc-500">Loading…</p>

  return (
    <div className="mt-12">
      <h1 className="text-2xl font-bold text-center mb-8">Quiz results</h1>

      <div className="grid grid-cols-3 gap-3 mb-8 text-center">
        {[
          [report.total_score, 'score', 'text-violet-400'],
          [`${report.accuracy_pct}%`, 'accuracy', ''],
          [
            report.avg_reaction_time_ms
              ? `${(report.avg_reaction_time_ms / 1000).toFixed(1)}s`
              : '—',
            'avg time',
            '',
          ],
        ].map(([val, label, color], i) => (
          <motion.div
            key={label}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: i * 0.12 }}
            className="bg-zinc-900 border border-zinc-800 rounded p-4"
          >
            <p className={`text-3xl font-mono font-bold ${color}`}>{val}</p>
            <p className="text-xs text-zinc-500 mt-1">{label}</p>
          </motion.div>
        ))}
      </div>

      <h2 className="font-semibold mb-3">By topic</h2>
      <div className="space-y-2 mb-8">
        {Object.entries(report.per_topic).map(([topic, r]) => (
          <div
            key={topic}
            className="flex justify-between items-center bg-zinc-900 border border-zinc-800 rounded px-4 py-2"
          >
            <span>{topic}</span>
            <span className="font-mono text-sm text-zinc-400">
              {r.correct}/{r.attempted} · {r.accuracy_pct}%
              <span className="text-zinc-600 ml-2">avg difficulty {r.avg_theta_q}</span>
            </span>
          </div>
        ))}
      </div>

      <DiagnosePanel sessionId={sessionId} />

      <div className="text-center">
        <Link
          to="/"
          className="inline-block bg-zinc-800 hover:bg-zinc-700 rounded px-6 py-2 font-semibold"
        >
          Back home
        </Link>
      </div>
    </div>
  )
}
