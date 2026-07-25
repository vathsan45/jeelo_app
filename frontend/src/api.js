const API = import.meta.env.VITE_API_BASE || 'http://localhost:8001'

async function request(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || `${res.status} ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  createPlayer: (name) =>
    request('/players/create', { method: 'POST', body: JSON.stringify({ name }) }),
  getPlayer: (playerId) => request(`/players/${playerId}`),

  placementStart: (playerId) =>
    request(`/placement/${playerId}/start`, { method: 'POST' }),
  placementNext: (sessionId) => request(`/placement/${sessionId}/next`),
  placementSubmit: (sessionId, body) =>
    request(`/placement/${sessionId}/submit`, { method: 'POST', body: JSON.stringify(body) }),
  placementSummary: (sessionId) => request(`/placement/${sessionId}/summary`),

  quizStart: (playerId, body) =>
    request(`/quiz/${playerId}/start`, { method: 'POST', body: JSON.stringify(body) }),
  quizNext: (sessionId) => request(`/quiz/${sessionId}/next`),
  quizSubmit: (sessionId, body) =>
    request(`/quiz/${sessionId}/submit`, { method: 'POST', body: JSON.stringify(body) }),
  quizSummary: (sessionId) => request(`/quiz/${sessionId}/summary`),

  arenaStart: (playerId, body) =>
    request(`/risk_arena/${playerId}/start`, { method: 'POST', body: JSON.stringify(body) }),
  arenaRound: (sessionId, n) => request(`/risk_arena/${sessionId}/round/${n}`),
  arenaSubmit: (sessionId, n, body) =>
    request(`/risk_arena/${sessionId}/round/${n}/submit`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  arenaCoachReport: (sessionId) => request(`/risk_arena/${sessionId}/coach_report`),

  getReport: (sessionId) => request(`/reports/${sessionId}`),
  failureTestStart: (sessionId, questionId) =>
    request(`/reports/${sessionId}/failure_test/${questionId}`, { method: 'POST' }),
  failureTestRespond: (sessionId, questionId, body) =>
    request(`/reports/${sessionId}/failure_test/${questionId}/respond`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
}

export const TOPICS = [
  'Mechanics',
  'Electricity and Magnetism',
  'Optics',
  'Modern Physics',
]
