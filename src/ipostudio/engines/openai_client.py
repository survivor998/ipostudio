"""Minimal OpenAI-compatible chat client for the running engine server
(public /v1/chat/completions protocol; llama-server documents the endpoint).
Non-streaming by design — streaming arrives with the conversation plan."""

import json
import math
import urllib.error
import urllib.request

from ipostudio.logs import redact_unambiguous


class ChatError(Exception):
    """A completion could not be produced; the message is user-safe."""

# one completion payload is a few KiB; 16 MiB leaves generous room for very
# long answers while still bounding what a runaway engine can make us buffer
_RESPONSE_BODY_CAP = 16 * 1024 * 1024

def chat_completion(
    host: str,
    port: int,
    *,
    model: str,
    prompt: str,
    temperature: float,
    top_p: float,
    top_k: int,
    repeat_penalty: float,
    timeout_s: float,
) -> dict:
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        # socket.settimeout rejects negatives/NaN with ValueError and inf
        # with OverflowError (time_t on Windows); inf is not a "no timeout"
        # sentinel anyway (None is) — the caller deserves the real diagnosis,
        # not a socket-internal crash or a hang (phase-3 targeted finding)
        raise ChatError(
            f"timeout must be a finite positive number of seconds, "
            f"got {timeout_s!r}"
        )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "repeat_penalty": repeat_penalty,
        "stream": False,
    }
    host_part = f"[{host}]" if ":" in host else host
    request = urllib.request.Request(
        f"http://{host_part}:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            # bound the read (cap + 1 byte detects truncation): a runaway or
            # hostile engine must not be able to drain memory with a huge or
            # slow-dripping body
            raw = response.read(_RESPONSE_BODY_CAP + 1)
    # HTTPError subclasses OSError: this arm must come first
    except urllib.error.HTTPError as exc:
        detail = exc.read(1024).decode("utf-8", errors="replace")[:500]
        raise ChatError(
            f"server returned HTTP {exc.code}: {redact_unambiguous(detail)}; "
            f"check `ipo server logs` for the engine output"
        ) from exc
    except urllib.error.URLError as exc:
        raise ChatError(
            f"cannot reach the server at {host}:{port} "
            f"({redact_unambiguous(str(exc.reason))}); start it with "
            f"`ipo server start`"
        ) from exc
    except OSError as exc:
        raise ChatError(
            f"cannot reach the server at {host}:{port} "
            f"({redact_unambiguous(str(exc))}); start it with "
            f"`ipo server start`"
        ) from exc
    if len(raw) > _RESPONSE_BODY_CAP:
        # never attempt to parse a truncated body
        raise ChatError(
            f"server response exceeded the read cap of {_RESPONSE_BODY_CAP} "
            f"bytes; the engine is not answering like a completions endpoint "
            f"— check `ipo server logs` for the engine output"
        )
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as exc:
        # RecursionError is not a ValueError: deeply nested payloads must
        # reach the caller as ChatError, never a bare traceback
        raise ChatError(
            f"server response was not valid JSON: {exc}; check "
            f"`ipo server logs` for the engine output"
        ) from exc
