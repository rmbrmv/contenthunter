# Market Research — Sources & Collection

## 📹 YouTube (YouTube Data API v3)
Use web_fetch to query:
```
https://www.googleapis.com/youtube/v3/search?part=snippet&q=openclaw&type=video&order=date&publishedAfter=YYYY-MM-DDT00:00:00Z&maxResults=10&key=AIzaSyAa8yy0GdcGPHdtD083HiGGx_S0vMPScDM
```

Second query with q="openclaw tutorial"

For video stats:
```
https://www.googleapis.com/youtube/v3/videos?part=statistics&id=VIDEO_ID1,VIDEO_ID2&key=AIzaSyAa8yy0GdcGPHdtD083HiGGx_S0vMPScDM
```

Calculate ER% = (likes + comments) / views × 100

### Top video transcripts
For top 2-3 by score, fetch transcript:
```
https://www.youtube.com/watch?v=VIDEO_ID
```
Use web_fetch(extractMode="text") → extract key points

## 🐙 GitHub
Releases:
```
https://api.github.com/repos/openclaw/openclaw/releases?per_page=5
```

Trending repos:
```
https://github.com/search?q=openclaw+created%3A>YYYY-MM-DD&type=repositories&sort=stars
```

## 🔧 ClawHub
```
https://clawhub.com/skills?sort=newest
https://clawhub.com/skills?q=multi-agent
https://clawhub.com/skills?q=automation
```

## 📰 Hacker News
```
https://hn.algolia.com/api/v1/search?query=openclaw&tags=story&numericFilters=created_at_i>TIMESTAMP
```
TIMESTAMP = Unix timestamp of (today - 2 days)

## 💬 Reddit
```
https://www.reddit.com/r/openclaw/new.json?limit=10
https://www.reddit.com/search.json?q=openclaw&sort=new&t=week&limit=10
```

## 📝 Medium / X
Usually blocked by JS. Try web_fetch, skip if fails.
