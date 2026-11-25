import os
import tempfile

os.environ.update(
    DATABASE_URL=f"sqlite:///{tempfile.mkdtemp()}/test.db", LLM_API_KEYS="k1,k2", MOCK_LLM="true",
    ENABLE_FAILURE_SIMULATION="true", LLM_MODEL="gemini/test",
)
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def chat(c, sid, msg, **kw):
    return c.post("/chat", json={"session_id": sid, "message": msg}, **kw)


def test_health(c):
    assert c.get("/health").json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_cache_across_sessions_and_different_message(c):
    a = chat(c, "s-a", "What is the capital of France?").json()
    b = chat(c, "s-b", "What is the capital of France?").json()
    d = chat(c, "s-c", "What is the capital of Spain?").json()
    assert a["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert b["metadata"]["resolution_source"] == "LLM_CACHE"
    assert b["reply"] == a["reply"] and b["metadata"]["key_id"] is None
    assert b["metadata"]["input_tokens"] == a["metadata"]["input_tokens"]
    assert d["metadata"]["resolution_source"] == "LIVE_INFERENCE" and d["reply"] != a["reply"]


def test_history_and_404(c):
    chat(c, "s-h", "hello there")
    chat(c, "s-h", "second message")
    msgs = c.get("/sessions/s-h/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert c.get("/sessions/nope/messages").status_code == 404


def test_failover(c):
    r = chat(c, "s-f", "failover please", headers={"X-Simulate-Failure": "key_1=429"})
    assert r.status_code == 200
    m = r.json()["metadata"]
    assert m["key_id"] == "key_2" and m["fallback_attempts"] == 1 and m["resolution_source"] == "LIVE_INFERENCE"
    assert chat(c, "s-f2", "x", headers={"X-Simulate-Failure": "key_1=500"}).json()["metadata"]["key_id"] == "key_2"


def test_all_fail_503_not_stored(c):
    r = chat(c, "s-503", "hi", headers={"X-Simulate-Failure": "*=429"})
    assert r.status_code == 503 and r.json() == {"detail": "all providers unavailable"}
    assert c.get("/sessions/s-503/messages").status_code == 404


@pytest.mark.parametrize("body", [{}, {"session_id": "s", "message": "   "}, {"session_id": "", "message": "x"},
                                  {"session_id": "s", "message": "x" * 4001}])
def test_422(c, body):
    assert c.post("/chat", json=body).status_code == 422


def test_malformed_json(c):
    r = c.post("/chat", content="{bad", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
