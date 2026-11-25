"""LiteLLM gateway: ordered key pool with failover + LiteLLM built-in response cache."""
import logging
import os

import litellm
from litellm import acompletion

log = logging.getLogger("llm")
litellm.drop_params = True


class AllProvidersFailed(Exception):
    pass


class SimulatedProviderError(Exception):
    def __init__(self, status: int):
        super().__init__(f"simulated provider error {status}")
        self.status_code = status


def model_name() -> str:
    return os.getenv("LLM_MODEL", "gemini/gemini-2.5-flash")


def get_keys() -> list[str]:
    return [k.strip() for k in os.getenv("LLM_API_KEYS", "").split(",") if k.strip()]


def cache_enabled() -> bool:
    return os.getenv("CACHE_ENABLED", "true").lower() == "true"


def setup_cache() -> None:
    if cache_enabled():
        if os.getenv("CACHE_TYPE", "local") == "disk":
            litellm.cache = litellm.Cache(type="disk", disk_cache_dir=os.getenv("CACHE_DIR", "/data/cache"))
        else:
            litellm.cache = litellm.Cache(type="local")
    else:
        litellm.cache = None


def parse_simulation(header: str | None) -> dict[str, int]:
    """'key_1=429,key_2=500' or '*=429' -> {'key_1': 429, ...}. Ignored unless enabled."""
    if not header or os.getenv("ENABLE_FAILURE_SIMULATION", "false").lower() != "true":
        return {}
    out = {}
    for part in header.split(","):
        k, _, v = part.strip().partition("=")
        if k and v.strip() in {"429", "500", "502", "503"}:
            out[k.strip()] = int(v)
    return out


async def complete(messages: list[dict], sim: dict[str, int]):
    """Try each key in order. Returns (response, cache_hit, key_id, fallback_attempts)."""
    failures = 0
    for i, key in enumerate(get_keys(), start=1):
        key_id = f"key_{i}"
        try:
            status = sim.get(key_id, sim.get("*"))
            if status:
                raise SimulatedProviderError(status)
            kwargs = dict(
                model=model_name(), messages=messages, api_key=key, temperature=0.2,
                num_retries=0, timeout=45,
                # simulated requests must hit a "real" key path, so bypass the cache for them
                caching=cache_enabled() and not sim,
            )
            if os.getenv("MOCK_LLM", "false").lower() == "true":  # tests only: no network
                kwargs["mock_response"] = f"Echo: {messages[-1]['content']}"
            resp = await acompletion(**kwargs)
            reply = resp.choices[0].message.content
            if not reply or not reply.strip():
                raise ValueError("empty completion")
            hit = bool((getattr(resp, "_hidden_params", None) or {}).get("cache_hit"))
            return resp, hit, key_id, failures
        except Exception as e:  # 429 / quota / 5xx / auth / timeout -> next key
            failures += 1
            log.warning("%s failed (%s: %s)", key_id, type(e).__name__, str(e)[:120])
    raise AllProvidersFailed()
