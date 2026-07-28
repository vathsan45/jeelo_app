// Local dev: FastAPI on 8001, routes mounted under /api (see backend main.py).
// Production (Vercel): set VITE_API_BASE=/api so requests stay same-origin
// and hit the /api(/.*)? rewrite to the backend service.
const API = import.meta.env.VITE_API_BASE || 'http://localhost:8001/api'

/**
 * Builds a bound `api` object whose every call attaches a fresh Clerk
 * session token as a Bearer header. `getToken` is Clerk's `useAuth().getToken`
 * — a function, not a value, since tokens are short-lived and must be
 * re-fetched (Clerk caches/refreshes internally) on every request rather
 * than captured once at login.
 */
export function createApi(getToken) {
  async function request(path, options = {}) {
    const token = await getToken()
    const res = await fetch(`${API}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...options,
    })
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}))
      throw new Error(detail.detail || `${res.status} ${res.statusText}`)
    }
    return res.json()
  }

  return {
    getMe: () => request('/players/me'),

    placementStart: () => request('/placement/start', { method: 'POST' }),
    placementNext: (sessionId) => request(`/placement/${sessionId}/next`),
    placementSubmit: (sessionId, body) =>
      request(`/placement/${sessionId}/submit`, { method: 'POST', body: JSON.stringify(body) }),
    placementSummary: (sessionId) => request(`/placement/${sessionId}/summary`),

    quizStart: (body) => request('/quiz/start', { method: 'POST', body: JSON.stringify(body) }),
    quizNext: (sessionId) => request(`/quiz/${sessionId}/next`),
    quizSubmit: (sessionId, body) =>
      request(`/quiz/${sessionId}/submit`, { method: 'POST', body: JSON.stringify(body) }),
    quizSummary: (sessionId) => request(`/quiz/${sessionId}/summary`),

    arenaStart: (body) =>
      request('/risk_arena/start', { method: 'POST', body: JSON.stringify(body) }),
    arenaRound: (sessionId, n) => request(`/risk_arena/${sessionId}/round/${n}`),
    arenaDecide: (sessionId, n, body) =>
      request(`/risk_arena/${sessionId}/round/${n}/decide`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    arenaAnswer: (sessionId, n, body) =>
      request(`/risk_arena/${sessionId}/round/${n}/answer`, {
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
}

export const TOPICS = [
  'Mechanics',
  'Electricity and Magnetism',
  'Optics',
  'Modern Physics',
]
