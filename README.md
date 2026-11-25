# LLM Chatbot with Key Failover and Response Caching

React + FastAPI + SQLite, with LiteLLM handling the key pool and response cache.

## 1. Live URLs
- Frontend: `<your frontend URL>`
- Backend: `<your backend URL>` (try `/health`)
- Repo: `<your GitHub URL>`

## 2. Run locally
**With Docker**
```bash
cp .env.example .env     # put at least 2 real keys in LLM_API_KEYS
make up                  # frontend :3000, backend :8000
make down
```
**Without Docker**
```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export LLM_API_KEYS=key1,key2 ENABLE_FAILURE_SIMULATION=true DATABASE_URL=sqlite:///./app.db
uvicorn app.main:app --port 8000
# new terminal
cd frontend && npm install && VITE_API_URL=http://localhost:8000 npm run dev
```
Backend tests: `make test` (uses LiteLLM `mock_response`, no network or keys).

## 3. Design decisions
- **Key fallback:** `LLM_API_KEYS` is an ordered pool (`key_1`, `key_2`, ...). Each request calls `litellm.acompletion` with the first key. Any failure (429, quota, 5xx, timeout, auth) moves to the next key; `fallback_attempts` counts the failures. If every key fails the API returns `503 {"detail":"all providers unavailable"}` and nothing is saved. Keys are never returned, only `key_id`.
- **Caching:** LiteLLM's built-in cache (`litellm.Cache`, in-memory by default, disk via `CACHE_TYPE=disk`). The cache key is the model plus the full message list (system + history + new message), so the same first message in a new session hits the cache and any different message misses. A hit is detected from LiteLLM's `cache_hit` flag and reported as `LLM_CACHE` with `key_id: null`, `fallback_attempts: 0` and the stored token usage. Requests carrying `X-Simulate-Failure` bypass the cache so failover can always be demonstrated.
- **SQLite sessions:** `messages` table as specified plus a small `sessions` table for the per-session system prompt. The schema is created on startup, the file lives at `DATABASE_URL` on a Docker volume (`/data`), and history is loaded per request so the client only sends the new message. A user/assistant pair is written in one transaction, only after a successful reply.
- **Tokens and latency:** taken from the response `usage` of that request only. Latency is measured server-side with `perf_counter`.

## 4. Verification
```bash
B=http://localhost:8000
curl $B/health
# live, then cache hit (new session, same message)
curl -s $B/chat -H 'Content-Type: application/json' -d '{"session_id":"a1","message":"What is the capital of France?"}'
curl -s $B/chat -H 'Content-Type: application/json' -d '{"session_id":"a2","message":"What is the capital of France?"}'
# failover: answered by key_2
curl -s $B/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: key_1=429' -d '{"session_id":"a3","message":"hello"}'
# every key fails: 503
curl -si $B/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: *=429' -d '{"session_id":"a4","message":"hello"}'
# history
curl -s $B/sessions/a1/messages
```
In the UI, open "Session settings" and type `key_1=429` in the simulate field to demo failover. Input and output tokens show beside every reply.

## 5. Setup Used
Editor: `<your editor>`. AI tools: Claude (scaffolding, review), LiteLLM docs.

## 6. Bonus features
- System prompt field per session.
- UI field for `X-Simulate-Failure` to demo failover without curl.
- Optional disk cache (`CACHE_TYPE=disk`).

## Deploying
- **Backend (Render, Docker):** root dir `backend`, set `LLM_API_KEYS`, `LLM_MODEL`, `ALLOWED_ORIGINS=<frontend URL>`, `ENABLE_FAILURE_SIMULATION=true`. Add a disk at `/data` if your plan allows it, otherwise history resets on redeploy.
- **Frontend (Vercel/Netlify):** root dir `frontend`, build `npm run build`, output `dist`, env `VITE_API_URL=<backend URL>`.
