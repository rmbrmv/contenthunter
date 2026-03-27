# Market Research Digest — Template

## Format for Telegram delivery

```
🦞 **Дайджест OpenClaw — DD марта 2026**

**🚀 Релизы:**
• vXXXX.X.X — краткое описание ключевых изменений
• Что важно для нас: [конкретное]

**📹 Топ видео (по ER% и глубине):**
• [Название](URL) — Xv, ER Y% — ключевой инсайт
• [Название](URL) — Xv, ER Y% — ключевой инсайт

**📰 Новости и статьи:**
• [Источник] Заголовок — что интересного

**💡 Фишки для нас (30 агентов):**
1. Конкретная рекомендация → что делать
2. Конкретная рекомендация → что делать

**🔍 Конкуренты:**
• Название — что появилось

**📁 Raw:** memory/market-research/YYYY-MM-DD-raw.md
```

## Scoring Rules
- ER% = (likes + comments) / views × 100
- Score = ER% × content_depth × relevance_to_us
- content_depth: short=1, tutorial=2, deep-dive=3
- relevance: generic=1, multi-agent=2, our-stack=3

## Filtering Rules
SKIP:
- Crypto/trading bots (unless architecture insight)
- Basic "install openclaw" tutorials
- Shorts < 60sec
- CRM/sales bots
- Non-English non-Russian without substance

KEEP:
- New OpenClaw releases + breaking changes
- Multi-agent patterns, orchestration
- Memory/context optimization
- Security advisories
- Competitor analysis
- Economy (token savings, model routing)
- Unusual/creative use cases

## Digest file
Save to: `memory/market-research/YYYY-MM-DD-digest.md`
Format:
```markdown
# Market Research Digest — DD месяц 2026

## Отправлено Роману ✅/❌

### Ключевое:
- bullet points

### Рекомендации:
1. numbered

### Отфильтровано:
- what was skipped and why
```
