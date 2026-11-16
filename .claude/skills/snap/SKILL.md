---
name: snap
description: Screenshot the app at phone and desktop width into process/screens/, dated and named, so the next process log entry and PR have evidence. Use after a UI change, before a test session, or when the user says "/snap", "screenshot the app", or "grab screenshots for the log".
argument-hint: "[what changed, e.g. 'timeline after the review'] [optional: routes or a URL]"
---

# /snap: dated screenshots for the process log

The process log is graded on evidence, and screenshots of each prototype are the easiest
evidence to forget. Before this skill they were taken by hand, at whatever width the
window happened to be, and named `Screenshot 2026-11-15 at 11.02.png`. This makes them
the same every time: both widths, the same routes, names that sort by date.

## What to capture

$ARGUMENTS

If no routes were given, capture these three:

| Route | What it shows |
|---|---|
| `/` | the home page and the topic box |
| `/demo` | the editor on the example lesson |
| the newest lesson the user has open, if they name one (`/l/<id>`) | the real editor |

Base URL: the live app if it's deployed (the URL in `README.md`), otherwise
`http://localhost:5173` (start it with `cd web && npm run dev` and the API with
`cd backend && uvicorn app.main:app --port 8000`). Ask which, if both exist and the user
didn't say.

## How

1. Use the browser tool you have (Claude in Chrome first, else Playwright).
2. For each route, at **390 x 844** (phone) and **1440 x 900** (desktop):
   - open it, wait until the page has settled (no spinner), and take a viewport screenshot;
   - on the editor, also take one with a scene selected that shows the change, if the change
     is in the editor.
3. Save each as `process/screens/YYYY-MM-DD-<slug>-<route>-<phone|desktop>.png`, where
   `<slug>` is two to four words from what changed (`timeline-after-review`) and `<route>`
   is `home`, `demo` or `lesson`. Never overwrite an existing file: add `-2`.
4. Look at every screenshot before saving it. If something is broken (an overflow, a cut-off
   caption, a blank stage), say so; don't hide it. Broken screenshots are evidence too.

## Then

- Print the files as Markdown image links, relative to the repo root, ready to paste into
  a `/reflect` entry or a PR description:
  `![Editor on a phone](process/screens/2026-11-16-timeline-after-review-demo-phone.png)`
- Don't commit them yourself. They go in with the PR or the `/reflect` entry they belong to.
- Never put a real person's name, face or email in a screenshot. If a lesson contains one,
  use `/demo` instead.
