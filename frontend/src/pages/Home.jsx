import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useUser } from '@clerk/clerk-react'
import { motion } from 'framer-motion'
import { TOPICS } from '../api.js'
import { useApi } from '../useApi.js'
import AnimatedNumber from '../components/AnimatedNumber.jsx'

export default function Home() {
  const navigate = useNavigate()
  const api = useApi()
  const { user } = useUser()
  const [profile, setProfile] = useState(null)
  const [topicFilter, setTopicFilter] = useState('')
  const [numQuestions, setNumQuestions] = useState(10)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.getMe().then(setProfile).catch((e) => setError(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function startPlacement() {
    setBusy(true)
    try {
      const { session_id } = await api.placementStart()
      navigate(`/placement/run/${session_id}`)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  async function startArena() {
    setBusy(true)
    try {
      const { session_id } = await api.arenaStart({ num_rounds: 8, first_session: true })
      navigate(`/arena/run/${session_id}`)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  async function startQuiz() {
    setBusy(true)
    try {
      const { session_id } = await api.quizStart({
        topic_filter: topicFilter || null,
        num_questions: Number(numQuestions),
      })
      navigate(`/quiz/run/${session_id}`)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <div className="mt-12">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Hi, {user?.firstName || profile?.name || 'there'}</h1>
        {profile && (
          <p className="text-zinc-400">
            Overall rating:{' '}
            <AnimatedNumber
              value={Math.round(profile.theta_overall)}
              from={1200}
              className="text-violet-400 font-mono font-bold"
            />{' '}
            <span className="text-zinc-500">(±{Math.round(profile.rd_overall)})</span>
          </p>
        )}
      </div>

      {profile && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-10">
          {TOPICS.map((t) => {
            const r = profile.topic_ratings[t]
            return (
              <div key={t} className="bg-zinc-900 border border-zinc-800 rounded p-3">
                <p className="text-xs text-zinc-500 mb-1">{t}</p>
                <p className="font-mono text-lg">
                  {r ? Math.round(r.theta_effective) : '—'}
                </p>
                <p className="text-xs text-zinc-600">
                  {r ? `${r.attempts_count} attempts` : ''}
                </p>
              </div>
            )
          })}
        </div>
      )}

      <motion.div
        className="space-y-6"
        initial="hidden"
        animate="show"
        variants={{ show: { transition: { staggerChildren: 0.12 } } }}
      >
        <motion.section
          variants={{ hidden: { opacity: 0, y: 14 }, show: { opacity: 1, y: 0 } }}
          className="bg-zinc-900 border border-zinc-800 rounded p-5"
        >
          <h2 className="font-semibold mb-1">Placement Quiz</h2>
          <p className="text-sm text-zinc-400 mb-4">
            8 questions across all topics to calibrate your rating. Do this first.
          </p>
          <button
            onClick={startPlacement}
            disabled={busy}
            className="bg-violet-600 hover:bg-violet-500 disabled:opacity-40 rounded px-5 py-2 font-semibold"
          >
            Start placement
          </button>
        </motion.section>

        <motion.section
          variants={{ hidden: { opacity: 0, y: 14 }, show: { opacity: 1, y: 0 } }}
          className="bg-zinc-900 border border-zinc-800 rounded p-5"
        >
          <h2 className="font-semibold mb-1">Practice Quiz</h2>
          <p className="text-sm text-zinc-400 mb-4">
            Adaptive questions matched to your rating. Scored +4 / −1.
          </p>
          <div className="flex flex-wrap gap-3 mb-4">
            <select
              value={topicFilter}
              onChange={(e) => setTopicFilter(e.target.value)}
              className="bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm"
            >
              <option value="">All topics</option>
              {TOPICS.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <select
              value={numQuestions}
              onChange={(e) => setNumQuestions(e.target.value)}
              className="bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm"
            >
              {[5, 10, 15].map((n) => (
                <option key={n} value={n}>{n} questions</option>
              ))}
            </select>
          </div>
          <button
            onClick={startQuiz}
            disabled={busy}
            className="bg-violet-600 hover:bg-violet-500 disabled:opacity-40 rounded px-5 py-2 font-semibold"
          >
            Start practice
          </button>
        </motion.section>

        <motion.section
          variants={{ hidden: { opacity: 0, y: 14 }, show: { opacity: 1, y: 0 } }}
          className="bg-zinc-900 border border-violet-800 rounded p-5"
        >
          <h2 className="font-semibold mb-1 text-violet-300">Risk Arena</h2>
          <p className="text-sm text-zinc-400 mb-4">
            8 rounds against 3 bots. Attempt (+4 / −1) or skip (0) under a
            countdown — smart risk-taking wins, not just knowledge.
          </p>
          <button
            onClick={startArena}
            disabled={busy}
            className="bg-violet-600 hover:bg-violet-500 disabled:opacity-40 rounded px-5 py-2 font-semibold"
          >
            Enter the arena
          </button>
        </motion.section>
      </motion.div>
      {error && <p className="text-red-400 mt-4">{error}</p>}
    </div>
  )
}
