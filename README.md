# IntelliNews Backend

Intelligent news aggregator backend built with **FastAPI**, **MongoDB**, and **Redis**. Powered by **HuggingFace** for AI-driven insights.


## Features

- **Automated RSS Pipeline**: Fetches, parses, and standardizes news from various XML feeds via automated async schedulers.
- **AI-Powered Summarization**: Generates in-depth 2-4 line summaries for every article using HuggingFace models.
- **Sentiment & Classification**: Automatically determines article sentiment (positive, neutral, negative) and categorizes articles.
- **Community Clubs**: Users can join pre-defined clubs, share articles to club feeds, and participate in nested/threaded comment discussions.
- **Advanced Bookmarking**: Save articles into customizable personal folders (e.g., "Tech News", "Research").
- **Gamification & Analytics**: Tracks user reading time and calculates trending articles based on views, upvotes, and recency.
- **Robust Authentication**: Secure JWT-based user authentication and profile management.
- **Location Filtering**: Support for fetching news based on specific global or regional locations.

## Tech Stack
- **Python 3.10+**
- **FastAPI**
- **MongoDB** 
- **Redis**
- **HuggingFace API** 

## API Endpoints Overview

| Route | Description |
|-------|-------------|
| `POST /auth/register` | Register new user |
| `POST /auth/login` | Login and get JWT |
| `GET /auth/me` | Retrieve user profile & gamification |
| `GET /article/` | List articles with infinite scroll, location, and date filters |
| `GET /article/personalized` | Get personalized feed |
| `GET /clubs/` | Discover and join community clubs |
| `POST /clubs/{slug}/posts` | Share articles or post text inside clubs |
| `GET /bookmarks/` | Retrieve user bookmarks and custom saved folders |

Full OpenAPI documentation is available at `http://localhost:8000/docs` when the server is running.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MONGODB_URL` | MongoDB connection string |
| `REDIS_URL` | Redis connection string |
| `HUGGINGFACE_API_KEY` | HuggingFace Access Token |
| `SECRET_KEY` | For JWT signing |

## Getting Started

### Local Development

1. Create a virtual environment: `python -m venv venv`
2. Activate it: `venv\Scripts\activate` (Windows)
3. Install dependencies: `pip install -r requirements.txt`
4. Run the server: `uvicorn app.main:app --reload`

### Docker Deployment

To deploy the Backendusing Docker:

1. Ensure Docker and Docker Compose are installed on your system.
2. From the **root** directory of the project, run:
   ```bash
   docker-compose up --build -d
   ```
3. The backend will be available at `http://localhost:8000` .
4. To view logs:
   ```bash
   docker-compose logs -f backend
   ```
5. To stop the containers:
   ```bash
   docker-compose down
   ```
