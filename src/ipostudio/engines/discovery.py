"""Locate the llama.cpp server executable.

ADR-010: a missing engine is reported honestly and never faked.  PATH lookup
uses shutil.which, which honors PATHEXT — `llama-server.exe` is found on
Windows without any platform branch (R1)."""

import shutil
from pathlib import Path

ENGINE_COMMAND = "llama-server"

def resolve_engine(configured: str) -> tuple[Path | None, str | None]:
    """Return (path, problem).  A configured path wins when it is a FILE (a
    directory would only fail later at Popen with a confusing "cannot start
    engine" instead of a config-point diagnosis); an empty setting falls
    back to PATH.  A configured path that does not exist is a hard problem —
    silently ignoring user configuration would start the wrong engine or
    quietly shadow it."""
    if configured.strip():
        path = Path(configured.strip()).expanduser()
        if path.is_file():
            return path, None
        return None, (
            f"configured engines.llama_cpp_path does not exist: {path}; "
            f"fix it with `ipo config set llama_cpp_path ...` or clear it "
            f"with `ipo config set llama_cpp_path \"\"` (empty falls back to PATH)"
        )
    found = shutil.which(ENGINE_COMMAND)
    if found:
        return Path(found), None
    return None, (
        f"llama.cpp server executable {ENGINE_COMMAND!r} not found on PATH; "
        f"install llama.cpp for your platform (see README quickstart) or set "
        f"the engines.llama_cpp_path config key"
    )
