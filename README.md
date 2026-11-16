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
3. **The Claude app** (claude.ai): a connector for public repositories (coming next).

## In this repository

- `PROCESS.md`: the design process log
- `PLAN.md`: the build plan, one pull request per slice
- `CLAUDE.md`: instructions for the coding agent
- `skill/lesson/`: the `/lesson` skill for Claude Code
