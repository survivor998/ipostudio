import sys
import time
import urllib.request
from pathlib import Path

import pytest

from ipostudio.engines.openai_client import ChatError, chat_completion
from ipostudio.engines.supervisor import choose_port

FAKE = Path(__file__).parent / "fake_llama_server.py"

@pytest.fixture
def fake_server():
    import subprocess

    port = choose_port("127.0.0.1", 18600)
    proc = subprocess.Popen(
        [sys.executable, str(FAKE), "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=1
            ) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(0.05)
    yield port
    proc.terminate()
    proc.wait(timeout=10)

def test_chat_completion_returns_choice_payload(fake_server):
    payload = chat_completion(
        "127.0.0.1", fake_server, model="fake", prompt="hi",
        temperature=0.2, top_p=0.9, top_k=40, repeat_penalty=1.1,
        timeout_s=10,
    )
    assert payload["choices"][0]["message"]["content"] == "echo:hi"

def test_chat_completion_down_server_raises_chat_error():
    with pytest.raises(ChatError) as excinfo:
        chat_completion(
            "127.0.0.1", 1, model="m", prompt="hi",
            temperature=0.2, top_p=0.9, top_k=40, repeat_penalty=1.1,
            timeout_s=0.5,
        )
    assert "cannot reach the server" in str(excinfo.value)
    assert "ipo server start" in str(excinfo.value)
