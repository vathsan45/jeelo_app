import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { api } from '../api.js'
import AnimatedNumber from '../components/AnimatedNumber.jsx'

export default function CoachReport() {
  const { sessionId } = useParams()
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)
  const [showLog, setShowLog] = useState(false)

  useEffect(() => {
    api.arenaCoachReport(sessionId).then(setReport).catch((e) => setError(e.message))
  }, [sessionId])

  if (error) return <p className="mt-24 text-center text-red-400">{error}</p>
  if (!report) return <p className="mt-24 text-center text-zinc-500">Crunching your decisions…</p>

  const bd = report.biggest_divergence

  return (
    <div className="mt-12">
      <h1 className="text-2xl font-bold text-center mb-2">Coach report</h1>
      <p className="text-center text-zinc-500 text-sm mb-8">
        how you played vs. perfectly calibrated risk-taking
      </p>

      <div className="text-center mb-10">
        <p className="text-zinc-500 text-sm uppercase tracking-wide">decision gap</p>
        <p className="text-6xl font-mono font-bold text-amber-400 my-2">
          {report.gap > 0 ? '-' : '+'}
          <AnimatedNumber value={Math.abs(Math.round(report.gap))} from={0} />
        </p>
        <p className="text-zinc-400">
          you scored <span className="font-mono">{report.actual_score}</span> · optimal play was
          worth <span className="font-mono">{report.optimal_score.toFixed(1)}</span>
        </p>
      </div>

      {report.final_leaderboard && (
        <div className="mb-8">
          <p className="text-xs text-zinc-500 uppercase tracking-wide mb-2">Final standings</p>
          <div className="space-y-1">
            {report.final_leaderboard.map((row, i) => (
              <div
                key={row.name}
                className={`flex justify-between rounded px-4 py-2 text-sm ${
                  row.is_player
                    ? 'bg-violet-950/50 border border-violet-700'
                    : 'bg-zinc-900 border border-zinc-800'
                }`}
              >
                <span>
                  <span className="text-zinc-500 mr-2">#{i + 1}</span>
                  {row.name}
                  {row.is_player && <span className="text-violet-400 ml-1">(you)</span>}
                </span>
                <span className="font-mono">{row.score}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {bd && (
        <div className="border border-amber-700 bg-amber-950/30 rounded-lg p-4 mb-8">
          <p className="text-amber-300 font-semibold text-sm mb-1">Your costliest call</p>
          <p className="text-sm text-zinc-300">
            Round {bd.round_num}: you {bd.attempted ? 'attempted' : 'skipped'} with a{' '}
            {(bd.p_success * 100).toFixed(0)}% win chance (breakeven is{' '}
            {(bd.breakeven * 100).toFixed(0)}%).{' '}
            {bd.attempted
              ? 'The odds were against you — that one was a skip.'
              : 'The odds were in your favor — that was worth a shot.'}
          </p>
        </div>
      )}

      <h2 className="font-semibold mb-3">Coaching points</h2>
      <ol className="space-y-2 mb-8">
        {report.coaching_points.map((p, i) => (
          <motion.li
            key={i}
            initial={{ opacity: 0, x: -16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.4 + i * 0.2 }}
            className="bg-zinc-900 border border-zinc-800 rounded p-3 text-sm"
          >
            <span className="text-violet-400 font-mono mr-2">{i + 1}.</span>
            {p}
          </motion.li>
        ))}
      </ol>

      <h2 className="font-semibold mb-3">By topic</h2>
      <div className="space-y-2 mb-8">
        {Object.entries(report.per_topic).map(([topic, t]) => (
          <div
            key={topic}
            className="flex justify-between bg-zinc-900 border border-zinc-800 rounded px-4 py-2 text-sm"
          >
            <span>
              {topic} <span className="text-zinc-600">({t.rounds} rounds)</span>
            </span>
            <span className="font-mono text-zinc-400">
              {t.actual} vs {t.optimal.toFixed(1)} optimal
            </span>
          </div>
        ))}
      </div>

      <button
        onClick={() => setShowLog(!showLog)}
        className="text-sm text-zinc-500 hover:text-zinc-300 mb-3"
      >
        {showLog ? '▾ hide' : '▸ show'} raw round log
      </button>
      {showLog && (
        <div className="space-y-1 mb-8 text-xs font-mono">
          {report.rounds.map((r) => (
            <div
              key={r.round_num}
              className={`flex justify-between rounded px-3 py-1.5 ${
                r.divergent ? 'bg-amber-950/40 text-amber-200' : 'bg-zinc-900/60 text-zinc-400'
              }`}
            >
              <span>
                R{r.round_num} · p={(r.p_success * 100).toFixed(0)}% ·{' '}
                {r.attempted ? (r.correct ? 'hit' : 'miss') : 'skip'}
              </span>
              <span>
                {r.points_delta >= 0 ? '+' : ''}
                {r.points_delta} (ev {r.optimal_ev})
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="text-center">
        <Link
          to="/"
          className="inline-block bg-violet-600 hover:bg-violet-500 rounded px-6 py-2 font-semibold"
        >
          Back home
        </Link>
      </div>
    </div>
  )
}
