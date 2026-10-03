import ipostudio


def test_version_is_semver_string():
    parts = ipostudio.__version__.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)
