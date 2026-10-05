"""`ipo chat` — one completion against the running server (spec §9.12 CLI
conversation, non-streaming slice).  Every attempt lands a completions row so
the M0' slice requirement (records survive restarts) holds for failures too."""

import time

import click

from ipostudio.cli.base import _fail, open_config_and_db
from ipostudio.engines.openai_client import ChatError, chat_completion
from ipostudio.engines.repo import active_instance, record_completion


@click.command("chat")
@click.argument("prompt", metavar="[PROMPT]")
@click.option("--timeout", "timeout_s", type=float, default=600.0,
              show_default=True,
              help="seconds before the completion gives up (spec §15 local budget)")
def chat(prompt: str, timeout_s: float) -> None:
    """Send one completion to the running server.

    PROMPT is the message text, or "-" to read stdin (for pipelines)."""
    if prompt == "-":
        import sys

        if sys.stdin is None:
            _fail("no stdin stream is available for '-'")
        prompt = sys.stdin.read()
    if not prompt.strip():
        _fail("empty prompt")
    conn, cfg = open_config_and_db()
    try:
        instance = active_instance(conn)
        if instance is None:
            _fail(
                "no server is running; start one with `ipo server start` "
                "(catalog: `ipo models`)"
            )
        if instance["state"] != "running":
            _fail(
                f"server is {instance['state']}, not ready; check `ipo status` "
                f"and `ipo server logs`"
            )
        started = time.monotonic()
        try:
            response = chat_completion(
                instance["host"], instance["port"],
                model=instance["model_name"], prompt=prompt,
                temperature=cfg.tuning.server_temp,
                top_p=cfg.tuning.server_top_p,
                top_k=cfg.tuning.server_top_k,
                repeat_penalty=cfg.tuning.server_repeat_penalty,
                timeout_s=timeout_s,
            )
        except ChatError as exc:
            _record_failure(conn, instance, prompt, started, str(exc))
            _fail(str(exc))
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        if not isinstance(content, str):
            # presence is not type-correctness: null/number/list must take
            # the error path, not crash on len() (Codex shape fold)
            _record_failure(conn, instance, prompt, started,
                            "malformed response payload")
            _fail("server returned a malformed response payload "
                  "(choices[0].message.content must be a string); check "
                  "`ipo server logs` for the engine output and `ipo status` "
                  "for its health")
        record_completion(
            conn, instance_id=instance["id"],
            model_name=instance["model_name"],
            prompt_text=prompt, output_text=content,
            prompt_chars=len(prompt), output_chars=len(content),
            duration_ms=int((time.monotonic() - started) * 1000),
            status="ok",
        )
    finally:
        conn.close()
    click.echo(content)

def _record_failure(conn, instance, prompt, started, detail: str) -> None:
    record_completion(
        conn, instance_id=instance["id"],
        model_name=instance["model_name"],
        prompt_text=prompt, prompt_chars=len(prompt), output_chars=0,
        duration_ms=int((time.monotonic() - started) * 1000),
        status="error", detail=detail[:500],
    )
