import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'

/** "Diagnose My Mistakes" section — works for any session (placement or practice). */
export default function DiagnosePanel({ sessionId }) {
  const navigate = useNavigate()
  const [report, setReport] = useState(null)

  useEffect(() => {
    api.getReport(sessionId).then(setReport).catch(() => {})
  }, [sessionId])

  if (!report || report.wrong_answers.length === 0) return null

  const slotsLeft = report.failure_tests_max - report.failure_tests_used

  return (
    <section className="border border-violet-800 bg-violet-950/30 rounded-lg p-5 mb-8 text-left">
      <h2 className="font-bold text-violet-300 mb-1">Diagnose My Mistakes</h2>
      <p className="text-sm text-zinc-400 mb-4">
        A short probing dialogue finds the exact step where your understanding
        broke down. {slotsLeft} of {report.failure_tests_max} diagnostics left
        this session.
      </p>
      <div className="space-y-3">
        {report.wrong_answers.map((w) => (
          <div key={w.question_id} className="bg-zinc-900 border border-zinc-800 rounded p-4">
            <p className="text-xs text-violet-400 mb-1">
              {w.topic} · {w.sub_topic} · difficulty {w.theta_q}
            </p>
            <p className="text-sm mb-2">{w.text}</p>
            <p className="text-xs text-zinc-500 mb-3">
              You answered <span className="text-red-400">{w.selected_answer}</span>
              {' '}· correct: <span className="text-green-400">{w.correct_answer}</span>
            </p>
            {w.diagnostic_status === 'diagnosed' ? (
              <button
                onClick={() => navigate(`/diagnose/${sessionId}/${w.question_id}`)}
                className="text-sm border border-violet-600 text-violet-300 rounded px-4 py-1.5"
              >
                View diagnosis
              </button>
            ) : (
              <button
                onClick={() => navigate(`/diagnose/${sessionId}/${w.question_id}`)}
                disabled={slotsLeft <= 0 && w.diagnostic_status === 'none'}
                className="text-sm bg-violet-600 hover:bg-violet-500 disabled:opacity-40 rounded px-4 py-1.5 font-semibold"
              >
                {w.diagnostic_status === 'in_progress' ? 'Continue diagnosis' : 'Diagnose'}
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
