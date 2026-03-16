# API Documentation

Base URL: `http://localhost:8000`

## Authentication

### POST /auth/register
Register a new user.
```json
{
  "email": "user@example.com",
  "username": "johndoe",
  "password": "securepass123",
  "full_name": "John Doe"
}
```

### POST /auth/login
```json
{
  "email": "user@example.com",
  "password": "securepass123"
}
```
**Response:** `{ "access_token": "...", "refresh_token": "...", "token_type": "bearer" }`

### POST /auth/refresh
```json
{ "refresh_token": "..." }
```

### GET /auth/me
Get current user profile. **Requires auth.**

### PUT /auth/me
Update user profile. **Requires auth.**

### POST /auth/logout
**Requires auth.**

---

## Articles

### GET /article/
List articles with pagination and filters.

| Param | Type | Description |
|-------|------|-------------|
| cursor | datetime | Pagination cursor |
| limit | int | Max 100, default 20 |
| category | string | Filter by category |
| tag | string | Filter by tag |
| sort_by | string | `new`, `old`, `top` |
| date_filter | string | `today`, `last_hour` |

### GET /article/personalized
Get personalized feed based on user preferences. **Requires auth.**

### GET /article/{article_id}
Get full article by ID.

### GET /article/{article_id}/similar
Get similar articles.

### POST /article/{article_id}/upvote
**Requires auth.**

### POST /article/{article_id}/downvote
**Requires auth.**

### POST /article/{article_id}/share
Track share interaction. **Requires auth.**

---

## Comments

### POST /comments/
Create comment. **Requires auth.**
```json
{
  "article_id": "...",
  "content": "Great article!",
  "parent_id": null
}
```

### GET /comments/{article_id}
Get all comments for an article.

### DELETE /comments/{comment_id}
Delete own comment. **Requires auth.**

### POST /comments/{comment_id}/upvote
**Requires auth.**

### POST /comments/{comment_id}/downvote
**Requires auth.**

---

## Bookmarks

### GET /bookmarks/
Get user's bookmarked articles. **Requires auth.**

### POST /bookmarks/{article_id}
Add bookmark. **Requires auth.**

### DELETE /bookmarks/{article_id}
Remove bookmark. **Requires auth.**

---

## Analytics

### GET /analytics/trending
Get trending articles.

### GET /analytics/top-categories
Get top categories by article count.

### GET /analytics/daily-counts
Get article counts per day.

### GET /analytics/reading-insights
Get user's reading insights. **Requires auth.**

### GET /analytics/dashboard
Get user dashboard stats. **Requires auth.**

---

## Vocabulary

### GET /vocab/today
Get today's vocab cards. **Requires auth.**

### POST /vocab/practice/done
Mark practice as done. **Requires auth.**
```json
{
  "words": ["word1", "word2"],
  "time_spent_minutes": 5
}
```

### GET /vocab/progress
Get vocab learning progress. **Requires auth.**

### POST /vocab/add
Add new vocab card. **Requires auth.**

---

## Admin

### POST /admin/refresh
Trigger news pipeline manually. **Requires admin.**

### POST /admin/refresh-breaking
Update breaking news flags. **Requires admin.**

### GET /admin/stats
Get system statistics. **Requires admin.**

---

## Health

### GET /
Health check.

### GET /health
Detailed health check.

---

## Authentication Header

For protected routes, include:
```
Authorization: Bearer <access_token>
```
