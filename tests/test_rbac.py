"""RBAC + key rotation (§24): roles, gates, and immediate invalidation."""
import pytest

from server import security


@pytest.fixture
def keys():
    """Snapshot and restore the mutable key state around every test."""
    saved = dict(security.KEYS)
    yield security.KEYS
    security.KEYS.clear()
    security.KEYS.update(saved)


def test_role_mapping(keys):
    keys["admin"], keys["analyst"] = "adm-k", "ana-k"
    assert security.role_of("adm-k") == "admin"
    assert security.role_of("ana-k") == "analyst"
    assert security.role_of("wrong") is None
    assert security.role_of("") is None


def test_analyst_gate_open_until_key_configured(keys):
    keys["admin"], keys["analyst"] = "adm-k", ""
    assert security.analyst_allowed("") is True            # gate not armed
    keys["analyst"] = "ana-k"
    assert security.analyst_allowed("") is False           # armed now
    assert security.analyst_allowed("ana-k") is True
    assert security.analyst_allowed("adm-k") is True       # admin passes everywhere


def test_rotation_invalidates_old_key_immediately(keys):
    keys["admin"] = "old-admin"
    new = security.rotate("admin")
    assert new != "old-admin" and len(new) == 48
    assert security.role_of("old-admin") is None
    assert security.role_of(new) == "admin"
    assert security.check_key(new) and not security.check_key("old-admin")


def test_rotation_mints_analyst_key_and_arms_gate(keys):
    keys["admin"], keys["analyst"] = "adm-k", ""
    assert security.analyst_allowed("")                    # open before mint
    minted = security.rotate("analyst")
    assert security.analyst_allowed(minted)
    assert not security.analyst_allowed("")                # armed after mint


def test_rotation_rejected_in_demo_open_mode(keys):
    keys["admin"] = ""
    with pytest.raises(RuntimeError):
        security.rotate("admin")


def test_rotation_audited_without_leaking_key(keys):
    keys["admin"] = "adm-k"
    before = len(security.AUDIT.entries)
    new = security.rotate("admin")
    entry = security.AUDIT.entries[-1]
    assert len(security.AUDIT.entries) == before + 1
    assert entry["action"] in ("key_rotated", "key_minted")
    assert new not in str(entry)                           # the key never enters the chain


def test_unknown_role_rejected(keys):
    keys["admin"] = "adm-k"
    with pytest.raises(ValueError):
        security.rotate("superuser")
