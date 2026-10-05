"""Minimal OpenAI-compatible chat client for the running engine server
(public /v1/chat/completions protocol; llama-server documents the endpoint).
Non-streaming by design — streaming arrives with the conversation plan."""

import json
import urllib.error
import urllib.request

from ipostudio.logs import redact_unambiguous


class ChatError(Exception):
    """A completion could not be produced; the message is user-safe."""

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
            return json.loads(response.read().decode("utf-8"))
    # HTTPError subclasses OSError: this arm must come first
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ChatError(
            f"server returned HTTP {exc.code}: {redact_unambiguous(detail)}"
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
    except ValueError as exc:
        raise ChatError(f"server response was not valid JSON: {exc}") from exc
