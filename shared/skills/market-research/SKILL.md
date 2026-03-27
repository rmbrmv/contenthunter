# Market Research — OpenClaw Daily Digest

## Trigger
Keywords: `ресёрч рынка`, `market research`, `дайджест openclaw`, `что нового в openclaw`

## Overview
Daily monitoring of OpenClaw ecosystem: YouTube, GitHub, ClawHub, HN, Reddit.
Extract actionable insights for ContentHunter (30+ agents deployment).

## Workflow

### Phase 1: Raw Data Collection
Read `reference/sources.md` for URLs and collection methods.

1. **YouTube** (web_fetch YouTube Data API): search "openclaw" + "openclaw tutorial", get stats (views, likes, ER%)
2. **GitHub** (web_fetch): releases, trending repos, new tools
3. **ClawHub** (web_fetch clawhub.com): new skills by category
4. **Hacker News** (web_fetch): search "openclaw" posts
5. **Reddit** (web_fetch): r/openclaw, r/ClaudeAI posts

Save raw data → `memory/market-research/YYYY-MM-DD-raw.md`

### Phase 2: Digest
Read `reference/digest-format.md` for template.

Filter raw data → actionable digest:
- Skip: crypto bots, basic tutorials, shorts, irrelevant CRM
- Keep: new releases, security fixes, techniques for multi-agent, memory, optimization
- Score videos: ER% × depth × relevance

Save digest → `memory/market-research/YYYY-MM-DD-digest.md`

### Phase 3: Delivery
Send digest to Roman via `message(action=send, target=295230564, channel=telegram)`
