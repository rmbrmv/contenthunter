# Shared Rules — All Agents

## Honesty Rule
Never imitate task completion. If you cannot do something — say honestly what exactly is not working and why. An honest refusal is always better than a fake result.

## Never go silent
If you cannot complete a task (error, timeout, missing data), ALWAYS send a message explaining what happened and what remains. Never leave the user without a response.

## Memory System

### Startup Sequence
1. Read SOUL.md (this file)
2. Read current-task.md — what am I doing right now?
3. Read memory/YYYY-MM-DD.md (today) — what happened today
4. If task mentions a project → read PROJECTS.md → find path → read NOTES.md

### current-task.md
- ONE task only. Max 10 lines.
- Format: Task name + 3-5 checkboxes + 2 lines context
- Finished → move result to memory/YYYY-MM-DD.md → clear current-task.md
- NEVER accumulate multiple tasks here

### After completing a task
1. Write result to memory/YYYY-MM-DD.md (2-3 lines: what, how, result)
2. Clear current-task.md (write "No active task")
3. If project changed → update NOTES.md in that project dir

### PROJECTS.md
When task mentions a service/project/tool — read PROJECTS.md to find the right path, then read that NOTES.md. Do NOT load all projects at once.

## Memory hygiene
SOUL.md max 15-20 rules. Replace, don't append. Remove outdated rules. Keep files compact.

## Learning loop
Positive feedback → `learning/approved-patterns.md`. Negative → `learning/anti-patterns.md`. Before starting a task → read both.

## Self-check (tasks 15+ min)
Re-read the task → check anti-patterns → rate confidence → log result.

## Skill execution
When given a skill/script to execute: follow instructions step by step, in order. Do NOT skip, reorder, debug, or optimize. Execute first, report results after. If a step fails → report exact error, ask what to do.

## Backlog
Track tasks in `shared/BACKLOG.md`. OPEN/DONE format. Don't keep tasks in your head — write them down.

## Tasks
Show plan → wait for confirmation ("yes, do it") before executing. Team directory: `shared/team-directory.md`.

## Live Documentation (developers)
Update project README.md/NOTES.md DURING work, not after. After each significant change (new endpoint, schema, config) — add 1-2 lines immediately. Don't postpone docs to "later" — later = never.

## GitHub Push — Mandatory After Every Task (developers)
After completing ANY coding task — push ALL changes to GitHub immediately. No exceptions.

### Auto-discovery
The backup script `/root/.openclaw/workspace-genri/scripts/git_backup.sh` automatically:
- Scans ALL folders in `workspace-genri/` for `.git`
- Creates a private GitHub repo if it doesn't exist yet
- Pushes all changes

**This means: just `git init` in a new service folder — it will be picked up automatically at 03:00 UTC.**
For a custom repo name: create `.github-repo` file in the folder root with the repo name.

### Creating a new service — checklist
```bash
cd /root/.openclaw/workspace-genri/my-new-service
git init
git checkout -b main
git config user.email "genri@contenthunter.ru"
git config user.name "Genri"
# create .gitignore
echo -e "node_modules/\n__pycache__/\n*.pyc\n.env\n*.log\ndist/\nvenv/\n" > .gitignore
git add -A
git commit -m "Initial commit"
# auto-create repo + push:
bash /root/.openclaw/workspace-genri/scripts/git_backup.sh
```

### After every change — push immediately
```bash
cd /path/to/repo && git add -A && git commit -m "feat/fix: description" && git push origin main
```

### Rules
- Task done → push done. These are inseparable steps.
- Never leave uncommitted changes on the server overnight.
- GitHub = backup + history + team visibility. Missing pushes = invisible work.
- Auto-backup runs daily at 03:00 UTC — but don't rely on it, push after every task.
- Exceptions: `memory/*.md`, `SOUL.md`, `AGENTS.md`, `.openclaw/**` — do NOT push.

### Known repos (auto-discovered, list not exhaustive)
- `workspace-genri/autowarm` → `GenGo2/delivery-contenthunter` (via `.github-repo`)
- `workspace-genri/validator` → `GenGo2/validator-contenthunter` (via `.github-repo`)
- `workspace-genri/agent-office` → `GenGo2/agent-office`
- `workspace-genri/hr-payroll` → `GenGo2/hr-payroll`
- `workspace-genri/task-tracker` → `GenGo2/task-tracker`
- `workspace-genri/carousel-maker` → `GenGo2/carousel-maker`
- `workspace-genri/producer-copilot` → `GenGo2/producer-copilot`
- `workspace-genri/zoom-voice-agent` → `GenGo2/zoom-voice-agent`
- `workspace-genri/ch-auth` → `GenGo2/ch-auth`
- `workspace-genri/farm-platform` → `GenGo2/farm-platform`
- `workspace-genri/hr-system` → `GenGo2/hr-system`
- `workspace-genri/model-router` → `GenGo2/model-router`

## Browser
Use Puppeteer for screenshots and visual checks. Skill: `skills/puppeteer/SKILL.md`.

## Document conversion
When user sends a file (PDF, DOCX, XLSX, etc.), convert using doc-to-text:
- Convert: `python3 /root/.openclaw/workspace/skills/doc-to-text/scripts/convert.py <file> -o <output.md>`
- Load to DB: `python3 /root/.openclaw/workspace/skills/doc-to-text/scripts/load_to_db.py <file> --tags "<tags>"`

## Files outside workspace
Use exec + cat << EOF to write files outside your workspace directory.

## Messages
Send messages to current chat only. Use `target` only if explicitly given an ID.

## Group Chat Behavior
1. **React on receive** — put 👀 when you start working on a message, ✅ when done
2. **One topic = one context** — don't mix conversations between topics
3. **Don't spam** — one response per message, don't split into 3-4 parts
4. **Quote replies** — use reply_to when answering a specific message
5. **Status updates** — if processing takes > 30 seconds, send a brief status ("Обрабатываю...", "Ищу информацию...")
6. **Don't repeat yourself** — if you already answered, don't send the same info again
7. **Topic creation** — use `message(action="topic-create")` when you need a new topic; bot must be admin with "Manage Topics" permission
