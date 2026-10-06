import sys
from pathlib import Path

import pytest

from ipostudio.conf.schema import ServerTuning
from ipostudio.engines.discovery import ENGINE_COMMAND, resolve_engine
from ipostudio.engines.llama_server import build_server_argv


def test_resolve_engine_configured_path_wins(tmp_path):
    engine = tmp_path / "llama-server.exe"
    engine.write_bytes(b"\x01")
    path, problem = resolve_engine(str(engine))
    assert (path, problem) == (engine, None)

def test_resolve_engine_configured_but_missing_is_a_problem(tmp_path):
    path, problem = resolve_engine(str(tmp_path / "gone"))
    assert path is None
    assert "does not exist" in problem
    assert "llama_cpp_path" in problem

def test_resolve_engine_rejects_directory_as_configured_path(tmp_path):
    # gstack F5: a directory used to pass `path.exists()` and failure was
    # deferred to Popen's confusing "cannot start engine"; it must fall
    # through to the same config-point diagnosis as a missing path
    path, problem = resolve_engine(str(tmp_path))
    assert path is None
    assert "llama_cpp_path" in problem
    assert "ipo config set" in problem

def test_resolve_engine_reports_missing_from_path(monkeypatch):
    monkeypatch.setenv("PATH", "")
    path, problem = resolve_engine("")
    assert path is None
    assert ENGINE_COMMAND in problem
    assert "install" in problem.lower()

def test_resolve_engine_finds_command_on_path(tmp_path, monkeypatch):
    # Windows' which() only matches PATHEXT names, POSIX only the bare name:
    # create both and accept either (R1: no platform branches, also in tests)
    for name in ("llama-server", "llama-server.exe"):
        candidate = tmp_path / name
        candidate.write_bytes(b"\x01")
        candidate.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    path, problem = resolve_engine("")
    assert problem is None
    # lower(): which() splices the PATHEXT entry verbatim and Windows stores
    # it as ".EXE" — the name casing is not part of the contract
    assert path is not None and path.name.lower() in ("llama-server", "llama-server.exe")

TUNING = ServerTuning()

def test_argv_carries_core_flags():
    argv = build_server_argv(
        Path("engine"), Path("m.gguf"), "127.0.0.1", 18080, TUNING, []
    )
    assert argv[:8] == ["engine", "--model", "m.gguf", "--host", "127.0.0.1",
                        "--port", "18080", "--ctx-size"]
    assert "8192" in argv and "--parallel" in argv
    assert "--cache-type-k" in argv and "q8_0" in argv

def test_argv_omits_auto_flags_and_appends_extras():
    argv = build_server_argv(
        Path("engine"), Path("m.gguf"), "h", 1, TUNING, ["--verbose", "--special", "v"]
    )
    assert "--flash-attn" not in argv  # auto -> engine default
    assert "--n-gpu-layers" not in argv
    assert argv[-3:] == ["--verbose", "--special", "v"]

def test_argv_flash_attn_on_and_explicit_gpu_layers():
    tuning = ServerTuning(server_flash_attn="on", server_gpu_layers=16)
    argv = build_server_argv(Path("e"), Path("m"), "h", 1, tuning, [])
    assert "--flash-attn" in argv and "on" in argv
    assert argv[argv.index("--n-gpu-layers") + 1] == "16"

def test_argv_cpu_mode_pins_zero_layers_only_without_explicit_count():
    cpu = build_server_argv(
        Path("e"), Path("m"), "h", 1, ServerTuning(server_load_mode="cpu"), []
    )
    assert cpu[cpu.index("--n-gpu-layers") + 1] == "0"
    both = build_server_argv(
        Path("e"), Path("m"), "h", 1,
        ServerTuning(server_load_mode="cpu", server_gpu_layers=5), [],
    )
    assert both.count("--n-gpu-layers") == 1
    assert both[both.index("--n-gpu-layers") + 1] == "5"

@pytest.mark.parametrize(
    ("extra", "managed"),
    [
        (["--port", "1"], True),
        (["--port=1"], True),
        (["-m", "x"], True),
        (["--model=y"], True),
        (["--host=h"], True),
        (["--ctx-size=1"], False),  # unmanaged: appended untouched
    ],
)
def test_argv_rejects_managed_flags_in_extras(extra, managed):
    def build():
        return build_server_argv(
            Path("engine"), Path("m.gguf"), "127.0.0.1", 18080, TUNING, extra
        )

    if managed:
        with pytest.raises(ValueError) as err:
            build()
        assert "managed flag" in str(err.value)  # error contract: names the problem
    else:
        assert build()[-1] == "--ctx-size=1"

def test_fake_engine_double_speaks_health_and_chat(tmp_path):
    """The fake engine is a subprocess contract: it must answer the two
    endpoints the core loop uses, on a port it is told to take."""
    import json
    import socket
    import subprocess
    import time
    import urllib.request

    fake = Path(__file__).parent / "fake_llama_server.py"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, str(fake), "--host", "127.0.0.1", "--port", str(port),
         "--model", "fake"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
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
        body = json.dumps(
            {"model": "fake", "messages": [{"role": "user", "content": "hi"}]}
        ).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode())
        assert payload["choices"][0]["message"]["content"] == "echo:hi"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
