"""Test double for llama-server (architecture.md §5: fake executables stand
in for real engines; no weights required).  Speaks the two endpoints the
core loop uses: GET /health and POST /v1/chat/completions."""

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--load-delay", type=float, default=0.0)
    parser.add_argument("--exit-immediately", action="store_true")
    args, _unknown = parser.parse_known_args()
    if args.exit_immediately:
        print("boom: simulated engine failure", file=sys.stderr)
        sys.exit(1)
    ready_at = time.monotonic() + args.load_delay

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/props":
                # stop-identity guard surface: names the served model so
                # `ipo server stop` can prove port ownership (Codex fold);
                # llama-server documents /props with the model path
                self._send(200, {"model_path": args.model})
            elif self.path == "/health":
                if time.monotonic() < ready_at:
                    self._send(503, {"error": {"message": "Loading model"}})
                else:
                    self._send(200, {"status": "ok"})
            else:
                self._send(404, {"error": {"message": "not found"}})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            prompt = ""
            for message in body.get("messages", []):
                if message.get("role") == "user":
                    prompt = message.get("content", "")
            self._send(
                200,
                {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion",
                    "model": body.get("model", args.model),
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": f"echo:{prompt}"},
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )

        def _send(self, code: int, payload: dict) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args) -> None:  # keep the engine log quiet
            pass

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.serve_forever()

if __name__ == "__main__":
    main()
