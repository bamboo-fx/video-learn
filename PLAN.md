# Build plan

One GitHub issue per slice, one branch and one pull request per issue. Slices in the same
lane can run at the same time in separate sessions once the storyboard schema (slice 2) is
merged, because everything else is built against it.

The course requirements each slice meets are numbered as in the project brief:
1 for someone, 2 frontend, 3 database, 4 deployed, 5 calls an LLM, 6 new API, 7 built with AI.

| # | Issue | Slice | Lane | Meets | Done when |
|---|---|---|---|---|---|
| 1 | this PR | This plan, and an issue per slice | | 7 | Issues exist; every later PR closes one |
| 2 | #1 | Storyboard schema: the contract between Claude, the voice and the editor | contract | | Pydantic models, a JSON Schema export, TypeScript types generated from it, an example storyboard that validates |
| 3 | #2 | Backend skeleton: FastAPI, SQLModel, Postgres, Docker, live on Railway | backend | 3, 4 | A project saved before a redeploy is still there after it, at a public https URL |
| 4 | #3 | Design system: palette, type, spacing, shadcn, the editor's layout shell | frontend | 2 | Tokens in one file, the shell at 390 px and 1440 px |
| 5 | #4 | Clickable mockup of the editor on a fake storyboard | frontend | 1, 2 | Someone who isn't Kevin can try it; then the first test round |
| 6 | #5 | Write the storyboard with Claude from a topic and pasted notes | backend | 5 | Topic in, valid scenes stored; a clear message when the model fails or isn't set up |
| 7 | #6 | Voice each scene with ElevenLabs, with word timings, cached by text | backend | 6 | Audio and timings stored in Postgres; a failed scene says so and can be retried |
| 8 | #7 | Player: scenes drawn in the browser, synced captions and reveals | frontend | 2 | Plays on a phone; a scene with no voice still plays with captions |
| 9 | #8 | Editor on the real API: edit narration or blocks, re-voice just that scene | both | 2, 3 | An edit survives a reload; only the edited scene is re-voiced |
| 10 | #9 | Edit with AI: Claude changes the storyboard through tools | both | 5 | "Make scene 3 simpler" changes scene 3 and nothing else, and shows what changed |
| 11 | #10 | Phone layout, accessibility, network failure states | frontend | 2 | Lab 6 standard on a phone on cell data |
| 12 | #11 | `/snap`: a skill that screenshots the live app into `process/` | harness | AI workflow | Every UI change has dated phone and desktop screenshots |

| 13 | #18 | Read a public GitHub repository into a cached snapshot | backend | 5, 6 | A repo link becomes source files keyed by commit; bad repos fail with a sentence |
| 14 | #19 | Claude researches the repo and cites real lines | backend | 5 | Every code scene is filled from the file; bad citations go back to Claude |
| 15 | #20 | Repo lessons in the editor | frontend | 1, 2 | Paste a repo and a question; see what Claude reads; code shows real line numbers |

Slices 13 to 15 narrow the product from any topic to a codebase: someone pastes a GitHub
repository they need to understand (often one an AI agent helped write) and asks about it.

After the design review: fixes from the group's worksheets, then quiz pauses (the lesson
stops, asks a question, and Claude checks the answer) and video export.

## Test points

These are where the design loop happens. Each ends with a `/reflect` entry.

- After slice 5: two or three people try the mockup. Write down what they did.
- The design review: photograph the three worksheets into `process/`.
- After the review fixes: retest the parts that changed.
