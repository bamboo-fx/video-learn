# Video Learn

Understand a codebase as a short narrated lesson you can watch and edit like a video.

Live: https://web-production-77637c10.up.railway.app

Final project for ENGR 190BO, AI-Amplified Prototyping (Harvey Mudd College, Fall 2026).

## Three ways to make a lesson

1. **The website.** Paste a public GitHub repository and ask a question.
2. **Claude Code, on your own code** (private repositories too). Install the `/lesson` skill:

   ```bash
   git clone --depth 1 https://github.com/bamboo-fx/video-learn.git /tmp/video-learn
   mkdir -p ~/.claude/skills && cp -R /tmp/video-learn/skill/lesson ~/.claude/skills/lesson
   ```

   Then, in Claude Code inside any repository: `/lesson how does login work?`, or
   `/lesson diff` to explain what changed on your branch.

   Your own Claude Code reads the code, so it costs the site nothing. A script next to the
   skill (`skill/lesson/lesson.py`, standard library only, worth reading before you install)
   keeps it safe:
   - it never reads `.env` files, keys or credentials;
   - code scenes are filled with the exact lines from your files;
   - lines that look like secrets are refused;
   - it shows you exactly what would be uploaded and waits for your yes.

   Only the lesson and the lines it shows leave your computer, never the repository. The
   link it prints makes the lesson yours in the first browser that opens it.
3. **The Claude app** (claude.ai), public repositories: add
   `https://web-production-77637c10.up.railway.app/mcp` as a custom connector (Settings,
   Connectors, Add custom connector), then ask Claude to "use Video Learn to make a lesson on
   github.com/owner/repo". Claude reads the repository through read-only tools and hands back
   a lesson link. It never asks for your GitHub account, and private repositories can't be read.

Setup steps for both: https://web-production-77637c10.up.railway.app/connect

## Editing a lesson

- **History.** Every change is kept as a version, like commits: Claude's writing, each AI
  edit, and your hand edits (a few minutes of typing is one version). Open the History tab to
  see what changed in each, look at an old version on the stage, go back to it, or name the
  lesson as it is now. Going back adds a version, so it can be undone too.
- **Editing together.** Share, then "Make an invite link". Whoever opens the link can edit the
  lesson with you; there are no accounts, so they type a name. Changes show up for everyone
  within a few seconds, and two people changing different things at once both keep their work.
- **Watching.** Speed from 0.5x to 2x, skip 10 seconds back or forward, and the usual keys:
  Space or K to play, arrows for 5 seconds, J and L for 10, < and > for speed.

## In this repository

- `PROCESS.md`: the design process log
- `PLAN.md`: the build plan, one pull request per slice
- `CLAUDE.md`: instructions for the coding agent
- `skill/lesson/`: the `/lesson` skill for Claude Code
