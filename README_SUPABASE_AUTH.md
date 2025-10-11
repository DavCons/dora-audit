
# Supabase Magic-Link Auth — Setup

## 1) Supabase Auth settings
- Go to **Supabase → Auth → URL Configuration**
- Set **Site URL** to your app base URL (e.g., `https://your.domain` or `http://<EC2-IP>:8501`)
- Add your base URL to **Redirect URLs**

## 2) Environment variables
Set these for the app service (Docker Compose or GHCR env):
```
SUPABASE_URL=https://<project-id>.supabase.co
SUPABASE_ANON_KEY=<your-anon-key>
APP_BASE_URL=https://your.domain  # or http://<EC2-IP>:8501 for testing
```

## 3) Flow
1. User enters email → app sends a magic link via Supabase.
2. User clicks the email link → returns to `APP_BASE_URL/?code=...`.
3. App exchanges the `code` for a Supabase session and lets the user in.

## 4) Docker Compose snippet
```yaml
services:
  streamlit-app:
    image: ghcr.io/<org>/<repo>-app:latest  # or build: ./app
    environment:
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_ANON_KEY=${SUPABASE_ANON_KEY}
      - APP_BASE_URL=${APP_BASE_URL}
    ports: ["8501:8501"]
    restart: unless-stopped
```
