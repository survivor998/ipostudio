"""Static guard for requirement R1: no POSIX-only constructs in src/.

The three-platform CI is the real gate once a remote exists; this test is the
local compensating guard until then (CEO review consensus, ADR-010).
"""

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

BANNED_PATTERNS = (
    "os.path.",          # use pathlib everywhere (plan Global Constraints)
    "if os.name ==",
    "sys.platform ==",
)


def test_no_posix_only_constructs_in_src():
    violations = []
    for py in SRC.rglob("*.py"):
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            for pattern in BANNED_PATTERNS:
                if pattern in line:
                    violations.append(f"{py.name}:{lineno}: {pattern.strip()}")
    assert not violations, "platform-hygiene violations:\n" + "\n".join(violations)
