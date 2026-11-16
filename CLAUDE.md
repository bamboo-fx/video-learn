# Video Learn

Type a topic (and paste your notes, if you have them), get a short narrated lesson you can
watch and edit like a video. Claude writes the lesson as a storyboard of scenes; ElevenLabs
voices each scene; the browser plays it with captions synced to the voice. You fix it by
hand on a timeline, or ask the AI to change one scene at a time.

Final project for ENGR 190BO (AI-Amplified Prototyping, HMC, Fall 2026). The project
brief's requirements and rubric are the spec: https://course.aiprototypes.org/resources/

## The one idea

Claude never outputs a finished video. It outputs and edits a **storyboard** (JSON: scenes,
each with a layout, on-screen blocks and narration). The editor renders the storyboard, and
the AI edits it through small tools (update a scene, insert, delete, reorder), so only the
scenes that changed get re-voiced and the person can still tweak everything by hand.

## Stack

- `backend/`: Python 3.12, FastAPI, SQLModel, Postgres. `requirements.txt`, not poetry/uv.
- `web/`: React, Vite, TypeScript, Tailwind, shadcn/ui. Built to static files and served
  by FastAPI, so the app is one service at one URL (no CORS). Storyboard types are generated
  from `shared/storyboard.schema.json` (`npm run gen:types`); never edit `storyboard.gen.ts`.
- Deploy: one Docker image on Railway, plus a Railway Postgres. Railway project
  "video-learn" in the personal "Kevin's Projects" workspace. Never link this repo to any
  other Railway project.
- Models: Claude (Anthropic API) for the storyboard and AI edits. ElevenLabs
  text-to-speech `with-timestamps` for narration and word timings.

## Run it

- API: `cd backend && ../.venv/bin/uvicorn app.main:app --port 8000` (SQLite unless `DATABASE_URL`).
- Web: `cd web && npm run dev` (port 5173, proxies `/api` to 8000). `/demo` needs no API.
- Tests: `cd backend && ../.venv/bin/pytest` (Claude and ElevenLabs are faked) and
  `cd web && npx tsc -b`.
- Paid calls: never run a real Claude or ElevenLabs call (beyond one smoke test) without
  Kevin's OK.

## Rules

- **Secrets live only in environment variables.** This repo is PUBLIC. Never commit a
  key, a `.env`, or a log that contains one. `.env.example` lists names with no values.
- **Call a model only on a user's action**, never on page load.
- **Every external call fails honestly.** If Claude or ElevenLabs fails, the page says what
  failed in plain words and keeps what the person already has. A missing key is a failure
  like any other ("AI writing isn't set up yet"), never a crash.
- **One task per session, one branch and one PR per slice.** Slices are GitHub issues;
  `PLAN.md` is the order. Small commits. Never push to `main` directly after the first
  commit; Kevin reads and merges every PR.
- **UI changes ship with screenshots** at phone width (390 px) and desktop (1440 px).
  The main task must work on a phone.
- **No grey skeleton blocks for first loads.** Nothing for 600 ms, then one small spinner
  and a line of text. Keep loaded content on screen while it refreshes.
- **Accessible by default.** Semantic HTML, labels on every control, visible focus,
  `role="status"` on loading regions, motion respects `prefers-reduced-motion`.

## Process log

`PROCESS.md` is graded on the design loop: what was tested, with whom, and what changed
because of it. Entries come from Kevin's own words through `/reflect`
(`.claude/skills/reflect/`). Never write, invent or backdate an entry, a person, a test, a
quote or a result. Photos and screenshots go in `process/`, linked from entries.

## Lessons

Add a line here each time the agent makes a mistake worth not repeating, with the date.

- 2026-11-15: The schema exporter stripped every key named `title`, which deleted the lesson's
  own `title` property along with JSON Schema's annotations. Treat property names under
  `properties` as data, never as keywords. The generated TypeScript type caught it.
- 2026-11-15: A local SQLite file (`backend/video-learn.db`) was committed with `git add backend`.
  `*.db` is ignored now. Stage paths you mean, and read `git status` before every commit.
- 2026-11-15: Tests share one database, and voice clips are cached by text, so a test that wants
  a voice *failure* must use narration no other test voiced.

## Skills

- `/reflect`: a process log entry from Kevin's words and the git history (from the course).
- `/snap`: dated phone and desktop screenshots into `process/screens/` for the log.
