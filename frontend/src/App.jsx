import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home.jsx'
import QuizRunner from './components/QuizRunner.jsx'
import PlacementSummary from './pages/PlacementSummary.jsx'
import QuizSummary from './pages/QuizSummary.jsx'
import Diagnose from './pages/Diagnose.jsx'
import Arena from './pages/Arena.jsx'
import CoachReport from './pages/CoachReport.jsx'

export default function App() {
  return (
    <div className="min-h-screen max-w-3xl mx-auto px-4 py-8">
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/placement/run/:sessionId" element={<QuizRunner mode="placement" />} />
        <Route path="/placement/summary/:sessionId" element={<PlacementSummary />} />
        <Route path="/quiz/run/:sessionId" element={<QuizRunner mode="practice" />} />
        <Route path="/quiz/summary/:sessionId" element={<QuizSummary />} />
        <Route path="/diagnose/:sessionId/:questionId" element={<Diagnose />} />
        <Route path="/arena/run/:sessionId" element={<Arena />} />
        <Route path="/arena/report/:sessionId" element={<CoachReport />} />
      </Routes>
    </div>
  )
}
