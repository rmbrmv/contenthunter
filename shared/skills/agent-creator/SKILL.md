---
name: agent-creator
description: Create a new OpenClaw agent with the correct workspace file structure (SOUL.md, AGENTS.md, MEMORY.md, TOOLS.md, IDENTITY.md, HEARTBEAT.md, BOOT.md, current-task.md, learning/). Use when creating a new agent from scratch. Triggers on phrases like "создай агента", "добавь агента", "новый агент", "create agent", "setup agent workspace".
---

# Agent Creator

Creates a properly structured agent workspace from a tested template.

## Quick Start

```bash
python3 /root/.openclaw/workspace/shared/skills/agent-creator/scripts/create_agent.py <agent_id> \
  --name "Имя агента" \
  --role "Role in English" \
  --project "Project Name" \
  --gender masculine|feminine
```

Examples:
```bash
python3 .../create_agent.py koordinator --name "Координатор" --role "Pipeline Coordinator" --project "Систематика v2" --gender masculine
python3 .../create_agent.py kritik1 --name "Критик 1" --role "Content Critic" --project "Систематика v2" --gender masculine
python3 .../create_agent.py elena-hr --name "Елена" --role "HR Business Partner" --project "Content Hunter" --gender feminine
```

## What Gets Created

```
/root/.openclaw/workspace-{agent_id}/
├── SOUL.md          ← pre-filled: name, role, project, gender
├── AGENTS.md        ← operational rules (universal)
├── TOOLS.md         ← local notes template
├── USER.md          ← user info (Roman + project)
├── IDENTITY.md      ← pre-filled: name, role, emoji
├── HEARTBEAT.md     ← periodic checks template
├── BOOT.md          ← gateway restart checklist
├── MEMORY.md        ← long-term memory (empty)
├── current-task.md  ← "No active task"
└── learning/
    ├── anti-patterns.md
    └── approved-patterns.md
```

## After Running the Script

1. **Edit SOUL.md** — fill in responsibilities, team table, project-specific rules
2. **Add to openclaw.json** — agents.list + telegram account + binding
3. **Restart gateway** — `openclaw gateway restart`
4. **Verify** — write to the bot in Telegram

See `shared/agent-template/HOW-TO-CREATE-AGENT.md` for full instructions including openclaw.json config examples.

## Notes

- Script auto-fills: `{Name}`, `{Role}`, `{Project}`, `{gender}`, `{verb1}`, `{verb2}`
- Remaining placeholders in SOUL.md (responsibilities, team table) must be edited manually
- Template source: `/root/.openclaw/workspace/shared/agent-template/`
