import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { api } from '../api.js'
import AnimatedNumber from './AnimatedNumber.jsx'

const ENDPOINTS = {
  placement: {
    next: api.placementNext,
    submit: api.placementSubmit,
    summaryPath: (sid) => `/placement/summary/${sid}`,
  },
  practice: {
    next: api.quizNext,
    submit: api.quizSubmit,
    summaryPath: (sid) => `/quiz/summary/${sid}`,
  },
}

export default function QuizRunner({ mode }) {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const ep = ENDPOINTS[mode]

  const [question, setQuestion] = useState(null)
  const [reveal, setReveal] = useState(null)
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [ratingBefore, setRatingBefore] = useState(null)
  const shownAt = useRef(null)

  const fetchNext = useCallback(async () => {
    setReveal(null)
    setSelected(null)
    setQuestion(null)
    try {
      const q = await ep.next(sessionId)
      if (q.complete) {
        navigate(ep.summaryPath(sessionId))
        return
      }
      setQuestion(q)
      shownAt.current = Date.now()
    } catch (err) {
      setError(err.message)
    }
  }, [ep, sessionId, navigate])

  useEffect(() => {
    fetchNext()
  }, [fetchNext])

  useEffect(() => {
    if (!question || reveal) return
    const t = setInterval(() => setElapsed(Date.now() - shownAt.current), 100)
    return () => clearInterval(t)
  }, [question, reveal])

  async function choose(option) {
    if (reveal || selected) return
    setSelected(option)
    try {
      const res = await ep.submit(sessionId, {
        question_id: question.question_id,
        selected_answer: option,
        reaction_time_ms: Date.now() - shownAt.current,
      })
      setRatingBefore(res.rating.theta_overall - res.rating.delta_overall)
      setReveal(res)
      setTimeout(fetchNext, 2000)
    } catch (err) {
      setError(err.message)
    }
  }

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

  if (!question) {
    return <p className="mt-24 text-center text-zinc-500">Loading…</p>
  }

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={question.question_id}
        initial={{ opacity: 0, x: 24 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -24 }}
        transition={{ duration: 0.25 }}
        className="mt-8"
      >
        <div className="flex justify-between text-sm text-zinc-500 mb-6">
          <span>
            {mode === 'placement' ? 'Placement' : 'Practice'} · Question{' '}
            {question.round} / {question.total}
          </span>
          <span className="font-mono text-violet-400">{(elapsed / 1000).toFixed(1)}s</span>
        </div>

        <p className="text-xs text-violet-400 mb-2">
          {question.topic} · {question.sub_topic}
        </p>
        <h2 className="text-lg mb-6 leading-relaxed">{question.text}</h2>

        <div className="space-y-3">
          {question.options.map((opt) => {
            let cls = 'bg-zinc-900 border-zinc-700 hover:border-violet-500'
            if (reveal) {
              if (opt === reveal.correct_answer) cls = 'bg-green-900/40 border-green-500'
              else if (opt === selected) cls = 'bg-red-900/40 border-red-500'
              else cls = 'bg-zinc-900 border-zinc-800 opacity-40'
            } else if (opt === selected) {
              cls = 'bg-violet-900/40 border-violet-500'
            }
            return (
              <motion.button
                key={opt}
                whileTap={{ scale: reveal ? 1 : 0.98 }}
                onClick={() => choose(opt)}
                disabled={!!reveal}
                className={`w-full text-left border rounded px-4 py-3 transition-colors ${cls}`}
              >
                {opt}
              </motion.button>
            )
          })}
        </div>

        <AnimatePresence>
          {reveal && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-6 text-center"
            >
              <p
                className={`text-lg font-bold ${
                  reveal.correct ? 'text-green-400' : 'text-red-400'
                }`}
              >
                {reveal.correct ? 'Correct!' : 'Wrong'}
              </p>
              {reveal.points_delta !== null && reveal.points_delta !== undefined && (
                <p className="text-zinc-400">
                  {reveal.points_delta > 0 ? '+' : ''}
                  {reveal.points_delta} points
                </p>
              )}
              <p className="text-sm text-zinc-500 mt-2">
                Rating{' '}
                <span
                  className={
                    reveal.rating.delta_overall >= 0 ? 'text-green-400' : 'text-red-400'
                  }
                >
                  {reveal.rating.delta_overall >= 0 ? '+' : ''}
                  {reveal.rating.delta_overall.toFixed(1)}
                </span>{' '}
                →{' '}
                <AnimatedNumber
                  value={reveal.rating.theta_overall}
                  from={ratingBefore}
                  className="font-mono text-violet-300 text-base font-bold"
                />
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </AnimatePresence>
  )
}
