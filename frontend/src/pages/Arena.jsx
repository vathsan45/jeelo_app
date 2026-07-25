import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { api } from '../api.js'
import AnimatedNumber from '../components/AnimatedNumber.jsx'

const ROUND_SECONDS = 15

export default function Arena() {
  const { sessionId } = useParams()
  const navigate = useNavigate()

  const [round, setRound] = useState(null)
  const [roundNum, setRoundNum] = useState(1)
  const [result, setResult] = useState(null)
  const [board, setBoard] = useState(null) // persists across rounds so reorders animate
  const [timeLeft, setTimeLeft] = useState(ROUND_SECONDS)
  const [error, setError] = useState(null)
  const [thetaBefore, setThetaBefore] = useState(null)
  const shownAt = useRef(null)
  const submitting = useRef(false)

  const loadRound = useCallback(
    async (n) => {
      setResult(null)
      setRound(null)
      submitting.current = false
      try {
        const r = await api.arenaRound(sessionId, n)
        setRound(r)
        setRoundNum(n)
        setTimeLeft(ROUND_SECONDS)
        shownAt.current = Date.now()
      } catch (e) {
        setError(e.message)
      }
    },
    [sessionId],
  )

  useEffect(() => {
    loadRound(1)
  }, [loadRound])

  const submit = useCallback(
    async (handRaised, selectedAnswer) => {
      if (submitting.current) return
      submitting.current = true
      try {
        const res = await api.arenaSubmit(sessionId, roundNum, {
          hand_raised: handRaised,
          reaction_time_ms: Date.now() - shownAt.current,
          selected_answer: selectedAnswer ?? null,
        })
        setThetaBefore((prev) => prev ?? res.player.effective_arena_theta)
        setResult(res)
        setBoard(res.leaderboard)
      } catch (e) {
        setError(e.message)
      }
    },
    [sessionId, roundNum],
  )

  useEffect(() => {
    if (!round || result) return
    if (timeLeft <= 0) {
      submit(false, null)
      return
    }
    const t = setTimeout(() => setTimeLeft((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [round, result, timeLeft, submit])

  if (error) {
    return (
      <div className="mt-24 text-center">
        <p className="text-red-400 mb-4">{error}</p>
        <button className="text-violet-400" onClick={() => navigate('/')}>
          Back home
        </button>
      </div>
    )
  }
  if (!round) return <p className="mt-24 text-center text-zinc-500">Loading…</p>

  const urgent = timeLeft <= 4
  const timerColor =
    timeLeft > 8 ? 'text-violet-400' : timeLeft > 4 ? 'text-amber-400' : 'text-red-500'

  return (
    <div className="mt-6">
      <AnimatePresence mode="wait">
        <motion.div
          key={roundNum}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -16 }}
          transition={{ duration: 0.25 }}
        >
          <div className="flex justify-between items-center mb-4">
            <span className="text-sm text-zinc-500">
              Risk Arena · Round {round.round} / {round.total}
            </span>
            {!result && (
              <motion.span
                key={timeLeft}
                initial={{ scale: urgent ? 1.35 : 1.1, opacity: 0.7 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ duration: 0.3 }}
                className={`font-mono text-3xl font-bold tabular-nums ${timerColor}`}
              >
                {timeLeft}
              </motion.span>
            )}
          </div>

          <div className="flex gap-3 text-xs text-zinc-400 mb-6">
            <span className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1">
              difficulty {round.theta_q}
            </span>
            <span className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1">
              +{round.marking_scheme.correct} correct · {round.marking_scheme.incorrect}{' '}
              wrong · 0 skip
            </span>
          </div>

          <p className="text-xs text-violet-400 mb-2">
            {round.topic} · {round.sub_topic}
          </p>
          <h2 className="text-lg mb-6 leading-relaxed">{round.text}</h2>

          {!result ? (
            <>
              <div className="space-y-3 mb-6">
                {round.options.map((opt) => (
                  <motion.button
                    key={opt}
                    whileTap={{ scale: 0.98 }}
                    onClick={() => submit(true, opt)}
                    className="w-full text-left border border-zinc-700 bg-zinc-900 hover:border-violet-500 rounded px-4 py-3 transition-colors"
                  >
                    {opt}
                  </motion.button>
                ))}
              </div>
              <button
                onClick={() => submit(false, null)}
                className="w-full border border-zinc-600 text-zinc-400 hover:text-zinc-200 rounded px-4 py-2"
              >
                Skip this one (0 points)
              </button>
            </>
          ) : (
            <RoundResult
              result={result}
              thetaBefore={thetaBefore}
              onNext={() =>
                result.session_complete
                  ? navigate(`/arena/report/${sessionId}`)
                  : loadRound(roundNum + 1)
              }
            />
          )}
        </motion.div>
      </AnimatePresence>

      {board && <LeaderboardStrip rows={board} />}
    </div>
  )
}

function LeaderboardStrip({ rows }) {
  return (
    <div className="mt-8">
      <p className="text-xs text-zinc-500 uppercase tracking-wide mb-2">Leaderboard</p>
      <div className="space-y-1">
        {rows.map((row, i) => (
          <motion.div
            key={row.name}
            layout
            transition={{ type: 'spring', stiffness: 350, damping: 28 }}
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
              {row.last_action && (
                <span
                  className={`ml-2 text-xs ${
                    row.last_action === 'correct'
                      ? 'text-green-400'
                      : row.last_action === 'wrong'
                        ? 'text-red-400'
                        : 'text-zinc-500'
                  }`}
                >
                  {row.last_action}
                </span>
              )}
            </span>
            <span className="font-mono">{row.score}</span>
          </motion.div>
        ))}
      </div>
    </div>
  )
}

function RoundResult({ result, thetaBefore, onNext }) {
  const p = result.player
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <div className="text-center mb-6">
        {p.attempted ? (
          <motion.p
            initial={{ scale: 0.7 }}
            animate={{ scale: 1 }}
            transition={{ type: 'spring', stiffness: 300, damping: 15 }}
            className={`text-2xl font-bold ${p.correct ? 'text-green-400' : 'text-red-400'}`}
          >
            {p.correct ? `Correct! +${p.points_delta}` : `Wrong ${p.points_delta}`}
          </motion.p>
        ) : (
          <p className="text-2xl font-bold text-zinc-400">Skipped · 0</p>
        )}
        <p className="text-sm text-zinc-500 mt-1">
          Answer: <span className="text-green-400">{result.correct_answer}</span>
        </p>
        <p className="text-xs text-zinc-500 mt-2">
          Arena rating:{' '}
          <AnimatedNumber
            value={p.effective_arena_theta}
            from={thetaBefore}
            className="font-mono text-violet-300 font-bold"
          />
        </p>
      </div>

      <div className="text-center">
        <button
          onClick={onNext}
          className="bg-violet-600 hover:bg-violet-500 rounded px-6 py-2 font-semibold"
        >
          {result.session_complete ? 'See coach report' : 'Next round'}
        </button>
      </div>
    </motion.div>
  )
}
