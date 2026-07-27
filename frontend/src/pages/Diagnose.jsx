import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { api } from '../api.js'

export default function Diagnose() {
  const { sessionId, questionId } = useParams()
  const navigate = useNavigate()

  const [phase, setPhase] = useState('loading') // loading | probing | reveal | fallback | error
  const [probes, setProbes] = useState([])
  const [steps, setSteps] = useState([])
  const [answered, setAnswered] = useState(0)
  const [selected, setSelected] = useState(null) // option just clicked, during the brief per-probe reveal
  const [lastFeedback, setLastFeedback] = useState(null) // { correct, correct_option }
  const [diagnosis, setDiagnosis] = useState(null)
  const [error, setError] = useState(null)
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return // StrictMode double-mount guard
    started.current = true
    api
      .failureTestStart(sessionId, questionId)
      .then((res) => {
        setSteps(res.solution_steps)
        if (res.fallback) {
          setPhase('fallback')
        } else {
          setProbes(res.probes)
          setAnswered(res.answered || 0)
          setPhase('probing')
        }
      })
      .catch((e) => {
        setError(e.message)
        setPhase('error')
      })
  }, [sessionId, questionId])

  const goBack = () => navigate(-1) // return to whichever summary launched this

  async function choose(option) {
    if (selected) return
    setSelected(option)
    const probe = probes[answered]
    try {
      const res = await api.failureTestRespond(sessionId, questionId, {
        step_order: probe.step_order,
        selected_option: option,
      })
      setLastFeedback({ correct: res.correct, correct_option: res.correct_option })
      setTimeout(() => {
        setSelected(null)
        setLastFeedback(null)
        if (res.complete) {
          setDiagnosis(res.diagnosis)
          setSteps(res.solution_steps)
          setPhase('reveal')
        } else {
          setAnswered(res.answered)
        }
      }, 900)
    } catch (e) {
      setError(e.message)
      setPhase('error')
    }
  }

  if (phase === 'loading') {
    return <p className="mt-24 text-center text-zinc-500">Preparing your diagnostic…</p>
  }
  if (phase === 'error') {
    return (
      <div className="mt-24 text-center">
        <p className="text-red-400 mb-4">{error}</p>
        <button className="text-violet-400" onClick={goBack}>
          Back to results
        </button>
      </div>
    )
  }

  if (phase === 'fallback') {
    return (
      <div className="mt-12">
        <h1 className="text-xl font-bold mb-2">Solution walkthrough</h1>
        <p className="text-sm text-zinc-400 mb-6">
          The interactive diagnostic is unavailable right now — here's the full
          correct solution instead.
        </p>
        <SolutionSteps steps={steps} gapStep={null} />
        <BackButton onClick={goBack} />
      </div>
    )
  }

  if (phase === 'probing') {
    const probe = probes[answered]
    return (
      <div className="mt-12">
        <p className="text-xs text-violet-400 uppercase tracking-wide mb-2">
          Diagnostic · checkpoint {answered + 1} of {probes.length}
        </p>
        <AnimatePresence mode="wait">
          <motion.div
            key={answered}
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -24 }}
            transition={{ duration: 0.25 }}
          >
            <h1 className="text-lg leading-relaxed mb-2">{probe.probe_question}</h1>
            <p className="text-xs text-zinc-600 mb-6">testing: {probe.concept_tested}</p>

            <div className="space-y-3">
              {probe.options.map((opt) => {
                let cls = 'bg-zinc-900 border-zinc-700 hover:border-violet-500'
                if (selected) {
                  if (opt === lastFeedback?.correct_option) {
                    cls = 'bg-green-900/40 border-green-500'
                  } else if (opt === selected) {
                    cls = 'bg-red-900/40 border-red-500'
                  } else {
                    cls = 'bg-zinc-900 border-zinc-800 opacity-40'
                  }
                }
                return (
                  <motion.button
                    key={opt}
                    whileTap={{ scale: selected ? 1 : 0.98 }}
                    onClick={() => choose(opt)}
                    disabled={!!selected}
                    className={`w-full text-left border rounded px-4 py-3 transition-colors ${cls}`}
                  >
                    {opt}
                  </motion.button>
                )
              })}
            </div>
          </motion.div>
        </AnimatePresence>
      </div>
    )
  }

  // reveal — the payoff moment: title fades in, steps cascade, then the gap
  // step lights up after the cascade lands
  const gapDelay = 0.5 + steps.length * 0.18
  return (
    <div className="mt-12">
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <p className="text-xs text-violet-400 uppercase tracking-wide mb-2">Diagnosis</p>
        <h1 className="text-xl font-bold mb-1">
          {diagnosis.gap_step_order
            ? `Your understanding broke down at step ${diagnosis.gap_step_order}`
            : 'No conceptual gap found'}
        </h1>
        <p className="text-zinc-300 mb-2">{diagnosis.gap_description}</p>
        <p className="text-xs text-zinc-500 mb-6">confidence: {diagnosis.confidence}</p>
      </motion.div>
      <SolutionSteps steps={steps} gapStep={diagnosis.gap_step_order} animated />
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: gapDelay + 0.6 }}
      >
        <BackButton onClick={goBack} />
      </motion.div>
    </div>
  )
}

function SolutionSteps({ steps, gapStep, animated = false }) {
  const gapDelay = 0.5 + steps.length * 0.18
  return (
    <ol className="space-y-2 mb-8">
      {steps.map((s, i) => {
        const isGap = gapStep === s.step_order
        return (
          <motion.li
            key={s.step_order}
            initial={animated ? { opacity: 0, x: -20 } : false}
            animate={{
              opacity: 1,
              x: 0,
              ...(isGap && animated
                ? {
                    borderColor: ['#27272a', '#27272a', '#ef4444'],
                    backgroundColor: [
                      'rgba(24,24,27,1)',
                      'rgba(24,24,27,1)',
                      'rgba(69,10,10,0.5)',
                    ],
                  }
                : {}),
            }}
            transition={{
              opacity: { delay: 0.4 + i * 0.18, duration: 0.3 },
              x: { delay: 0.4 + i * 0.18, duration: 0.3 },
              borderColor: { delay: gapDelay, duration: 0.5 },
              backgroundColor: { delay: gapDelay, duration: 0.5 },
            }}
            className={`border rounded p-3 ${
              isGap && !animated
                ? 'border-red-500 bg-red-950/40'
                : 'border-zinc-800 bg-zinc-900'
            }`}
          >
            <p className="text-sm">
              <span className="text-zinc-500 mr-2">step {s.step_order}</span>
              {s.step_text}
            </p>
            {(s.formula_used || s.concept_tested) && (
              <p className="text-xs text-zinc-500 mt-1">
                {s.formula_used && <span className="mr-3">formula: {s.formula_used}</span>}
                {s.concept_tested && <span>concept: {s.concept_tested}</span>}
              </p>
            )}
            {isGap && (
              <motion.p
                initial={animated ? { opacity: 0, scale: 0.9 } : false}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: animated ? gapDelay + 0.3 : 0, duration: 0.3 }}
                className="text-xs text-red-400 font-semibold mt-2"
              >
                ← this is where it went wrong
              </motion.p>
            )}
          </motion.li>
        )
      })}
    </ol>
  )
}

function BackButton({ onClick }) {
  return (
    <div className="text-center">
      <button
        onClick={onClick}
        className="bg-zinc-800 hover:bg-zinc-700 rounded px-6 py-2 font-semibold"
      >
        Back to results
      </button>
    </div>
  )
}
