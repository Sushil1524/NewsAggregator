# News Aggregator Backend

Intelligent news aggregator with AI-powered summarization.

## Features

- RSS feed aggregation from multiple sources
- AI-powered article summarization
- User authentication with JWT tokens
- Personalized news feed based on preferences
- Analytics and trending articles
- Comments and discussions
- Bookmarks

## API Endpoints

| Route | Description |
|-------|-------------|
| `POST /auth/register` | Register new user |
| `POST /auth/login` | Login and get JWT |
| `GET /article` | List articles |
| `GET /article/personalized` | Personalized feed |
| `GET /analytics/trending` | Trending articles |
| `POST /admin/refresh` | Trigger RSS fetch |

Full documentation at `/docs` when running.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_KEY` | Supabase anon key |
| `MONGODB_URL` | MongoDB connection string |
| `REDIS_URL` | Redis connection string |
| `HUGGINGFACE_API_KEY` | HuggingFace API key |
| `SECRET_KEY` | JWT signing key |
