# JEE Physics Adaptive Learning — Frontend

Vite + React + Tailwind v4 + React Router + Framer Motion. No component
library — everything is hand-styled utility classes plus a handful of shared
components.

## Setup & run

```powershell
cd frontend
npm install
npm run dev
```

Opens on http://localhost:5173 (or the next free port — Vite tries 5174, 5175,
... automatically if 5173 is taken; the backend's CORS policy accepts any
localhost port, so this just works).

Expects the backend running at `http://localhost:8001/api` by default
(routes are mounted under `/api` — see `backend/README.md`). Override with a
`VITE_API_BASE` environment variable (e.g. in a `.env` file or your shell) if
the backend is elsewhere.

`npm run build` produces a static `dist/` bundle; nothing here needs
server-side rendering.

## Deploying to Vercel

This service is the `frontend` entry in the project-root `vercel.json`. Set
`VITE_API_BASE=/api` in this service's Vercel environment variables — a
relative, same-origin path that hits the `/api(/.*)?` rewrite to the backend
service, rather than the local-dev default of `localhost:8001`.

---

## File-by-file

### `src/main.jsx`

The React entrypoint. Mounts `<App />` into `#root` wrapped in
`<BrowserRouter>` (so every page can use `useNavigate`/`useParams`/`<Link>`)
and `<StrictMode>` (React's double-invoke-effects-in-dev safety net — this is
why `Diagnose.jsx` needs an explicit guard against double-firing its startup
effect, see below).

### `src/index.css`

`@import "tailwindcss";` pulls in Tailwind v4 (configured via the Vite plugin
in `vite.config.js`, not a `tailwind.config.js` file — v4 doesn't require one
for a default setup). One manual rule sets the page background/text color for
the dark theme (`bg-zinc-950 text-zinc-100`).

### `src/App.css`

**Unused leftover from the Vite React scaffold.** Nothing in the app imports
it (confirmed — `App.jsx` was rewritten from scratch and never re-added the
import). Safe to delete; kept only because deleting untouched scaffold files
wasn't part of any phase's task.

### `src/App.jsx`

The route table — the only file that knows the full site map. Wraps every
page in a `max-w-3xl mx-auto` centered column (the "one focused screen at a
time" layout principle from the Phase 5 spec). Routes:

| Path | Component | Purpose |
|---|---|---|
| `/` | `Home` | name entry, rating overview, mode launchers |
| `/placement/run/:sessionId` | `QuizRunner` (mode="placement") | placement question loop |
| `/placement/summary/:sessionId` | `PlacementSummary` | rating reveal + diagnose panel |
| `/quiz/run/:sessionId` | `QuizRunner` (mode="practice") | practice question loop |
| `/quiz/summary/:sessionId` | `QuizSummary` | score/accuracy + diagnose panel |
| `/diagnose/:sessionId/:questionId` | `Diagnose` | failure-testing probe/reveal flow |
| `/arena/run/:sessionId` | `Arena` | risk arena round loop |
| `/arena/report/:sessionId` | `CoachReport` | risk arena payoff screen |

### `src/api.js`

The single fetch layer — no component calls `fetch()` directly. `request(path,
options)` prepends `API` (from `VITE_API_BASE`, default
`http://localhost:8001`), sets the JSON content-type header, and on a non-2xx
response, parses whatever error body the backend returned and throws an
`Error` with the backend's `detail` message (falling back to
`"<status> <statusText>"` if the body isn't JSON) — this is what shows up
verbatim in every page's `error` state. Exports one `api` object with a method
per backend endpoint (`createPlayer`, `getPlayer`, `placementStart/Next/
Submit/Summary`, `quizStart/Next/Submit/Summary`, `arenaStart/Round/Submit/
CoachReport`, `getReport`, `failureTestStart/Respond`) plus a `TOPICS` constant
listing the four sub-topics in the fixed order they should always display in
(Mechanics, Electricity and Magnetism, Optics, Modern Physics).

### `src/components/AnimatedNumber.jsx`

The single reusable "counting up/down" number — every place a rating changes
on screen uses this instead of a static `{value}`. Built on Framer Motion's
`useMotionValue` (a mutable animatable value outside React's render cycle) and
`useTransform` (derives a rounded integer from it so partial decimals never
flash on screen). An effect calls `animate(mv, value, {...})` every time the
`value` prop changes, tweening from the motion value's *current* position
(not from React state) to the new target over 0.9s with an `easeOut` curve —
this is what makes a rating that updates twice in quick succession animate
smoothly through both changes rather than snapping. The `from` prop only
matters on first mount (seeds the motion value's starting position, e.g. `1200`
for "count up from the default starting rating"); it's ignored on subsequent
re-renders since the motion value already has its own live position by then.
Rendering `<motion.span>{rounded}</motion.span>` directly — Framer Motion
subscribes the DOM text content to the motion value's changes without
round-tripping through React state on every animation frame, which is both
simpler and faster than the naive `useState` + `requestAnimationFrame`
approach.

### `src/components/QuizRunner.jsx`

The shared question-loop component for **both** placement and practice quiz —
one component, driven by an `ENDPOINTS` lookup table keyed by the `mode` prop
(`"placement"` or `"practice"`) that maps to the right `next`/`submit`
API calls and the right summary route to navigate to on completion. This is
the concrete implementation of the spec's "share one QuizRunner component"
instruction.

- State: `question` (current question payload or `null` while loading),
  `reveal` (the submit response, present only during the post-answer pause),
  `selected` (which option the player clicked), `elapsed` (live-updating
  reaction-timer display, ticked by a `setInterval` that only runs while a
  question is showing and unrevealed), `ratingBefore` (captured once per
  question so `AnimatedNumber` knows where to animate *from* — computed as
  `new_theta - delta` from the submit response rather than a second API call).
- `fetchNext()` calls the mode-appropriate `next` endpoint; if it returns
  `{complete: true}`, navigates to the mode-appropriate summary route instead
  of rendering a question — this is the loop's natural exit.
- `choose(option)` — guards against double-submission (`if (reveal ||
  selected) return`), submits with the actual elapsed reaction time in
  milliseconds, then schedules `fetchNext` via `setTimeout(fetchNext, 2000)` —
  the fixed 2-second pause is the "brief correct/incorrect reveal transition"
  the spec asked for before auto-advancing.
- Rendering: `AnimatePresence mode="wait"` keyed on `question.question_id`
  slides each new question in from the right and the previous one out to the
  left (a lightweight "next card" transition, not decorative motion — it
  signals "this is a new, different question" every time). Option buttons
  color-code once `reveal` is set: green border on the correct answer, red on
  a wrong selection, dimmed on everything else. The reveal panel shows
  correct/wrong, the scored `points_delta` (only rendered if not
  `null`/`undefined` — placement omits this per spec since it's unscored), and
  the rating delta with an `AnimatedNumber` counting from `ratingBefore` to the
  new overall rating.

### `src/components/DiagnosePanel.jsx`

The "Diagnose My Mistakes" section, extracted into its own component so both
`PlacementSummary` and `QuizSummary` can show it identically (originally built
only into `QuizSummary`; moved out here after confirming the backend's report
endpoint is mode-agnostic, so placement's wrong answers deserve the same
diagnostic treatment as practice quiz's). Fetches `api.getReport(sessionId)`
itself on mount — the two summary pages don't need to know or pass down report
data. Renders nothing (`return null`) if there are no wrong answers to
diagnose. For each wrong answer, shows the question, the player's answer vs.
the correct one, and a button that routes to `/diagnose/{sessionId}/
{questionId}` — labeled "Diagnose" (not started), "Continue diagnosis"
(probes generated but not all answered), or "View diagnosis" (already
complete, un-styled as primary since there's nothing left to do). The button
is disabled only when the 3-per-session budget (`failure_tests_max -
failure_tests_used`) is exhausted **and** this particular question hasn't been
started yet — a question already in progress or complete stays clickable even
if the budget is spent on other questions.

### `src/pages/Home.jsx`

The landing/hub screen — also owns lightweight "session" persistence via
`localStorage` (key `"player"`) since there's no real auth. `getStoredPlayer()`
is exported so other files could read it if needed (not currently used
elsewhere, but kept as the single source of truth for the storage key/shape).

- No stored player → renders just a name field and "Start" button, which
  calls `api.createPlayer(name)`, stores the returned `{player_id, name, ...}`
  in `localStorage`, and re-renders into the logged-in view.
- Stored player → fetches the live profile via `api.getPlayer` on mount; if
  that 404s (e.g. `data/app.db` was deleted and reseeded, so the stored
  `player_id` no longer exists), clears `localStorage` and falls back to the
  name-entry view rather than showing a broken profile.
- The logged-in view shows the animated overall rating (`AnimatedNumber` from
  `1200`, so a returning player's very first paint still shows the count-up
  from the default), a 4-card topic-rating grid (`TOPICS` from `api.js`,
  showing `—` and no attempt count for topics the player hasn't touched yet),
  and three staggered (`framer-motion` `variants` with `staggerChildren`)
  launcher cards: Placement (`startPlacement`), Practice Quiz (`startQuiz`,
  with topic-filter and question-count `<select>`s that default to "all
  topics" / 10 questions), and Risk Arena (`startArena`, fixed at 8 rounds /
  `first_session: true` — the archetype-variety option Phase 4's API supports
  isn't exposed in this UI, since a hackathon demo only needs the fixed
  lineup). Each launcher navigates to that mode's `run` route on success.
- "switch player" clears `localStorage` and drops back to name entry — the
  only way to change players in this build (no player list/login screen).

### `src/pages/PlacementSummary.jsx`

Fetches `api.placementSummary(sessionId)` on mount. Shows the big animated
overall rating (`AnimatedNumber` from `1200` — placement's very purpose is to
move you off the default, so animating from exactly that default is the right
"before" state), the RD/confidence value, a staggered 4-card per-topic
breakdown (each card's entrance delayed by `0.3 + i*0.1`s so they cascade in
left-to-right), the shared `<DiagnosePanel>` (for placement questions
answered wrong — placement has no scoring but still has right/wrong answers
worth diagnosing), and a "Continue" link back to `/`.

### `src/pages/QuizSummary.jsx`

Fetches `api.getReport(sessionId)` (the detailed-report endpoint, not the
simpler `quizSummary` — chosen because the report endpoint additionally
carries `wrong_answers` and the failure-test budget counters that this screen
and `DiagnosePanel` both need). Three staggered stat tiles (score, accuracy,
avg reaction time — built from a small inline array mapped over so the same
entrance-animation code isn't repeated three times), a per-topic accuracy +
average-difficulty-faced list, the shared `<DiagnosePanel>`, and a "Back home"
link.

### `src/pages/Diagnose.jsx`

The failure-testing interactive flow — the "standout feature" screen, given
its own dedicated route rather than living inside the summary page.

- `phase` state machine: `loading` → (`probing` ⇄ answering each probe) →
  `diagnosing` (waiting on the final interpretation call) → `reveal`; or
  `loading` → `fallback` if the backend couldn't generate probes at all; or
  → `error` on any request failure. Each phase renders completely different
  content, so the component is effectively four small screens in one file
  rather than one screen with many conditionals scattered through it.
- The mount effect calls `api.failureTestStart` exactly once, guarded by a
  `started` ref (`if (started.current) return`) — necessary because
  `<StrictMode>` in development deliberately double-invokes effects to surface
  side-effect bugs, and without this guard the app would fire two real Groq
  API calls (and, worse, since the backend's start endpoint isn't
  idempotent-safe against true concurrent calls in the same way it is against
  sequential ones, could create two diagnostics) every time this page loads.
- `submitResponse` sends the current probe's response, flips to `diagnosing`
  *before* awaiting the response only when this is the last probe (so the
  "Analyzing…" pulsing state shows immediately rather than after a delay), and
  either advances `answered` (more probes left) or stores the final
  `diagnosis` and switches to `reveal`.
- `goBack` uses `navigate(-1)` (browser-style back) rather than a hardcoded
  route, so returning works correctly regardless of whether this diagnosis was
  launched from the placement summary or the quiz summary.
- **The reveal animation** (the deliberately dramatic moment the spec asked
  for): the diagnosis title/description fades in first, then `SolutionSteps`
  cascades each step in with a staggered delay (`0.4 + i*0.18`s per step), and
  only *after* the last step has landed (`gapDelay = 0.5 + steps.length*0.18`)
  does the step matching `diagnosis.gap_step_order` animate its border and
  background color from neutral zinc to red, followed shortly after by the
  "← this is where it went wrong" tag popping in with a scale animation. The
  `animated` prop on `SolutionSteps` lets the exact same component render
  statically (no animation, gap step just rendered red immediately) when it's
  reused for the `fallback` phase, where there's no diagnosis to build
  suspense toward.

### `src/pages/Arena.jsx`

The Risk Arena round loop.

- `ROUND_SECONDS = 15` — the fixed per-round countdown.
- State: `round` (current round payload), `result` (submit response, present
  during the between-rounds pause), `board` (the leaderboard array — kept in
  its **own** state slice, separate from `result`, specifically so
  `LeaderboardStrip` can live *outside* the `AnimatePresence key={roundNum}`
  block that remounts every round; if the leaderboard were only inside
  `result`, Framer Motion's `layout` reordering animation would have nothing
  to animate *from*, since the whole strip would unmount and remount fresh
  each round instead of persisting and reordering in place), `timeLeft`,
  `thetaBefore` (captured once, on the very first round's submit, from the
  response's `effective_arena_theta` — used only for the initial
  `AnimatedNumber`'s starting position, since subsequent rounds already have a
  live motion-value position to animate from).
- `loadRound(n)` fetches round `n`, resets `result` to `null`, and resets the
  countdown to 15.
- `submit(handRaised, selectedAnswer)` is guarded by a `submitting` ref against
  double-firing (e.g. a click racing the countdown's auto-skip), posts the
  actual elapsed reaction time, and stores both `result` and `board` from the
  response.
- The countdown effect ticks `timeLeft` down every second while a round is
  active and unresolved; **hitting zero auto-calls `submit(false, null)`** —
  an unanswered round is a forced skip, not a stuck screen.
- `urgent = timeLeft <= 4` drives both the color ramp (violet → amber → red at
  the 8s and 4s thresholds) and a punchier pop-in scale animation on the digit
  itself in the final stretch — the "visibly and urgently tick down" behavior
  from the spec.
- Between rounds, `RoundResult` shows the correct/wrong/skipped outcome (a
  spring-animated pop-in on the verdict text), the answer reveal, and the
  animated effective arena rating; `LeaderboardStrip` (rendered as a sibling,
  not a child, for the reason above) gives every row a `layout` prop, so
  Framer Motion automatically computes and animates a smooth position
  transition whenever `board`'s row order changes between renders — no manual
  reorder animation code needed. The "Next round" / "See coach report" button
  routes onward based on `result.session_complete`.

### `src/pages/CoachReport.jsx`

The Risk Arena payoff screen. Fetches `api.arenaCoachReport(sessionId)` on
mount. Layout follows the spec's prescribed order exactly: the headline
decision-gap number first (`AnimatedNumber` counting up from 0, sign-flipped
so a positive gap — meaning the player left points on the table — displays as
a leading `-`), the final leaderboard snapshot, a plain-English "costliest
call" callout built from `biggest_divergence` (phrases itself differently
depending on whether the costly call was an over-eager attempt or an
overly-cautious skip), the three LLM-generated coaching points (staggered
fade-in), a per-topic actual-vs-optimal-EV breakdown, and the raw round-by-
round log collapsed behind a "show/hide" toggle (`showLog` state) with
divergent rounds visually flagged in amber — kept last and collapsed per the
spec's "sequential focus reads better live" principle, since it's the most
detailed/least essential-at-a-glance section.
