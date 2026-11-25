import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints

from . import db, llm

logging.basicConfig(level=logging.INFO)
DEFAULT_SYSTEM_PROMPT = os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful, concise assistant.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    llm.setup_cache()
    yield


app = FastAPI(title="LLM Chatbot", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    system_prompt: Optional[str] = None


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    logging.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/health")
async def health():
    if not db.ping():
        raise HTTPException(503, "database unavailable")
    keys = llm.get_keys()
    if not keys:
        raise HTTPException(503, "key pool empty")
    return {"status": "ok", "keys_configured": len(keys), "cache_enabled": llm.cache_enabled()}


@app.post("/chat")
async def chat(req: ChatRequest, x_simulate_failure: Optional[str] = Header(default=None)):
    start = time.perf_counter()
    history = [{"role": m["role"], "content": m["content"]} for m in db.get_history(req.session_id)]
    sys_prompt = req.system_prompt if req.system_prompt is not None else db.get_system_prompt(req.session_id)
    sys_prompt = (sys_prompt or "").strip() or DEFAULT_SYSTEM_PROMPT
    messages = [{"role": "system", "content": sys_prompt}, *history, {"role": "user", "content": req.message}]

    try:
        resp, hit, key_id, failures = await llm.complete(messages, llm.parse_simulation(x_simulate_failure))
    except llm.AllProvidersFailed:
        raise HTTPException(503, "all providers unavailable")

    usage = getattr(resp, "usage", None)
    reply = resp.choices[0].message.content.strip()
    metadata = {
        "resolution_source": "LLM_CACHE" if hit else "LIVE_INFERENCE",
        "model": llm.model_name(),
        "latency_ms": max(1, int((time.perf_counter() - start) * 1000)),
        "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "key_id": None if hit else key_id,
        "fallback_attempts": 0 if hit else failures,
    }
    db.save_turn(req.session_id, req.message, reply, metadata,
                 req.system_prompt.strip() if req.system_prompt is not None else None)
    return {"session_id": req.session_id, "reply": reply, "metadata": metadata}


@app.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str):
    msgs = db.get_history(session_id)
    if not msgs:
        raise HTTPException(404, "session not found")
    return {"session_id": session_id, "messages": msgs}
