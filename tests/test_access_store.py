import time

import pytest

from app import access_store


@pytest.fixture(autouse=True)
def isolated_access_db(tmp_path, monkeypatch):
    monkeypatch.setenv("HFSTREAM_ACCESS_DB", str(tmp_path / "access.sqlite3"))
    monkeypatch.setenv("HFSTREAM_AUTH_SECRET", "test-only-secret")
    access_store.initialize()


def test_code_claim_starts_24_hour_session_and_allows_relogin_any_device():
    code = access_store.issue_code("discord-user-1")
    now = int(time.time())

    redeemed = access_store.redeem_code(code, "device-one", "ip-one")
    assert redeemed is not None
    assert now + 23 * 60 * 60 < redeemed["expires_at"] <= now + 24 * 60 * 60 + 5

    token = access_store.create_access_session(
        redeemed["code_hash"],
        redeemed["discord_user_id"],
        redeemed["expires_at"],
    )
    assert access_store.get_access_session(token, "device-one") is not None
    assert access_store.get_access_session(token, "device-two") is not None
    assert access_store.redeem_code(code, "device-two", "ip-two")["expires_at"] == redeemed["expires_at"]
    assert access_store.redeem_code(code, "device-one", "ip-one")["expires_at"] == redeemed["expires_at"]


def test_new_discord_code_reuses_active_code_within_24_hours(monkeypatch):
    start = 1_700_000_000
    monkeypatch.setattr(access_store.time, "time", lambda: start)
    first_code = access_store.issue_code("discord-user-2")

    # Ayni kullanici 24 saat icinde tekrar isterse ayni kodu almali
    second_code = access_store.issue_code("discord-user-2")
    assert first_code == second_code

    # 24 saat dolunca yeni kod uretilmeli
    monkeypatch.setattr(access_store.time, "time", lambda: start + 24 * 3600 + 1)
    third_code = access_store.issue_code("discord-user-2")
    assert third_code != first_code


def test_session_and_code_expire_at_configured_duration(monkeypatch):
    access_store.update_settings([], 1)
    start = 2_000_000_000
    monkeypatch.setattr(access_store.time, "time", lambda: start)
    code = access_store.issue_code("discord-user-3")
    redeemed = access_store.redeem_code(code, "device", "ip")
    assert redeemed is not None
    assert redeemed["expires_at"] == start + 3600
    token = access_store.create_access_session(
        redeemed["code_hash"],
        redeemed["discord_user_id"],
        redeemed["expires_at"],
    )

    monkeypatch.setattr(access_store.time, "time", lambda: start + 3601)
    assert access_store.get_access_session(token, "device") is None
    assert access_store.redeem_code(code, "device", "ip") is None


def test_revoking_code_invalidates_its_active_session():
    code = access_store.issue_code("discord-user-4")
    redeemed = access_store.redeem_code(code, "device", "ip")
    assert redeemed is not None
    token = access_store.create_access_session(
        redeemed["code_hash"],
        redeemed["discord_user_id"],
        redeemed["expires_at"],
    )

    assert access_store.revoke_code(redeemed["code_hash"])
    assert access_store.get_access_session(token, "device") is None


def test_oauth_state_is_bound_to_nonce_and_single_use():
    access_store.save_oauth_state("state-value", "nonce-value")

    assert not access_store.consume_oauth_state("state-value", "wrong-nonce")
    assert access_store.consume_oauth_state("state-value", "nonce-value")
    assert not access_store.consume_oauth_state("state-value", "nonce-value")


def test_code_entry_rate_limit_is_enforced():
    for _ in range(12):
        assert access_store.redeem_code("00000000000000", "device", "same-ip") is None

    with pytest.raises(access_store.AccessRateLimitError):
        access_store.redeem_code("00000000000000", "device", "same-ip")


def test_export_and_import_full_database():
    # Insert a user and comment
    access_store.upsert_google_user("g-export-1", "user@test.com", "Test User", "https://img.com/1")
    comm = access_store.add_video_comment("vid-101", "g-export-1", "Test User", "https://img.com/1", "Harika bir video!", rating=9, video_title="Film 101")
    assert comm is not None

    # Export database
    dump = access_store.export_full_database()
    assert dump["version"] == 1
    assert "tables" in dump
    assert len(dump["tables"]["google_users"]) >= 1
    assert len(dump["tables"]["video_comments"]) >= 1

    # Clear and re-import
    result = access_store.import_full_database(dump)
    assert result["status"] == "success"
    assert result["imported_rows"] > 0

    # Verify comments still exist
    reloaded_comms = access_store.list_video_comments("vid-101")
    assert len(reloaded_comms) >= 1
    assert reloaded_comms[0]["comment"] == "Harika bir video!"
