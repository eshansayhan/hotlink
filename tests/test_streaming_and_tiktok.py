import pytest

from app.streamer.loop import loop_controller
from app.streamer.ffmpeg import FFmpegStreamer
from app.streamer.nimo import nimo_manager
from app.streamer.tiktok import tiktok_manager
from app.streamer.tiktok_generator import TikTokStreamGenerator
from app.config import AppConfig, config


def _allow_tiktok_session(monkeypatch):
    monkeypatch.setattr(
        TikTokStreamGenerator,
        "validate_session",
        classmethod(lambda cls, session_cookie: (True, "TikTok oturumu doğrulandı.")),
    )


def test_local_video_loop_does_not_force_real_time_mode():
    flags = loop_controller.get_input_flags(is_url=False, enable_loop=True)

    assert "-re" not in flags
    assert "-stream_loop" in flags
    assert "-1" in flags


def test_nimo_destination_preserves_signed_key_query_and_masks_status(monkeypatch):
    stream_key = "sample-token?guid=abc&room=123&psign=secret-signature"
    monkeypatch.setattr(config, "nimo_enabled", True)
    monkeypatch.setattr(config, "nimo_rtmp_url", "rtmp://alpush.rtmp.nimo.tv/live/")
    monkeypatch.setattr(config, "nimo_stream_key", stream_key)

    assert nimo_manager.validate_credentials() == (True, "")
    assert nimo_manager.get_destination_url() == f"rtmp://alpush.rtmp.nimo.tv/live/{stream_key}"
    assert stream_key not in nimo_manager.get_status()["masked_destination"]


def test_local_env_overrides_base_and_persists_settings_locally(tmp_path, monkeypatch):
    import app.config as config_module

    base_env = tmp_path / ".env"
    local_env = tmp_path / ".env.local"
    base_env.write_text(
        "NIMO_ENABLED=false\n"
        "NIMO_RTMP_URL=rtmp://base.example/live/\n"
        "NIMO_STREAM_KEY=base-key\n",
        encoding="utf-8",
    )
    local_env.write_text(
        "NIMO_ENABLED=true\n"
        "NIMO_RTMP_URL=rtmp://local.example/live/\n"
        "NIMO_STREAM_KEY=local-key?guid=one&psign=two\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "ENV_FILE", base_env)
    monkeypatch.setattr(config_module, "LOCAL_ENV_FILE", local_env)
    for name in ("NIMO_ENABLED", "NIMO_RTMP_URL", "NIMO_STREAM_KEY"):
        monkeypatch.setenv(name, "")

    local_config = AppConfig()
    assert local_config.nimo_enabled is True
    assert local_config.nimo_rtmp_url == "rtmp://local.example/live/"
    assert local_config.nimo_stream_key == "local-key?guid=one&psign=two"

    updated_key = "updated-key?guid=two&psign=three"
    local_config.update({"nimo_stream_key": updated_key})

    assert updated_key in local_env.read_text(encoding="utf-8")
    assert "base-key" in base_env.read_text(encoding="utf-8")


def test_tiktok_create_room_resets_stale_session_before_retry(monkeypatch):
    calls = []
    _allow_tiktok_session(monkeypatch)

    monkeypatch.setattr(
        TikTokStreamGenerator,
        "clean_cookie_string",
        classmethod(lambda cls, raw: "sessionid=abc123"),
    )
    monkeypatch.setattr(
        TikTokStreamGenerator,
        "get_current_room_info",
        classmethod(lambda cls, session_cookie: {"room_id": "old_room", "live_status": 4, "is_live": False}),
    )
    monkeypatch.setattr(
        config,
        "reset_tiktok_session",
        lambda persist=True: calls.append(("reset", persist)),
    )
    monkeypatch.setattr(
        config,
        "update",
        lambda updates, persist=True: calls.append(("update", updates, persist)),
    )

    class DummyResp:
        status_code = 200

        def json(self):
            return {
                "status_code": 0,
                "data": {
                    "id_str": "new_room",
                    "stream_url": {
                        "rtmp_push_url": "rtmp://push.example.com/stage/stream-1234?foo=bar"
                    },
                },
            }

    monkeypatch.setattr("app.streamer.tiktok_generator.requests.post", lambda *args, **kwargs: DummyResp())

    ok, data, msg = TikTokStreamGenerator.create_room_and_get_key("sessionid=abc123", title="24/7 Test")

    assert ok is True
    assert ("reset", True) in calls
    assert data["room_id"] == "new_room"


def test_tiktok_event_url_normalizes_to_event_id():
    event_url = (
        "https://www.tiktok.com/live/event/7693683878724272135"
        "?enter_from=share_link&share_from_user_id=7234995656510686213"
    )

    assert TikTokStreamGenerator.normalize_event_id(event_url) == "7693683878724272135"
    assert TikTokStreamGenerator.normalize_event_id("7693683878724272135") == "7693683878724272135"
    with pytest.raises(ValueError):
        TikTokStreamGenerator.normalize_event_id("https://example.com/live/event/7693683878724272135")


def test_tiktok_session_validation_uses_account_api_and_returns_no_account_data(monkeypatch):
    requests_seen = []

    class AccountInfoResponse:
        ok = True
        status_code = 200

        def json(self):
            return {"status_code": 0, "data": {"user_id_str": "123456789"}}

    def fake_get(url, **kwargs):
        requests_seen.append((url, kwargs))
        return AccountInfoResponse()

    monkeypatch.setattr("app.streamer.tiktok_generator.requests.get", fake_get)

    valid, message = TikTokStreamGenerator.validate_session("sessionid=private-test-cookie")

    assert valid is True
    assert message == "TikTok oturumu doğrulandı."
    assert len(requests_seen) == 1
    assert requests_seen[0][0] == TikTokStreamGenerator.SESSION_INFO_URL
    assert requests_seen[0][1]["headers"]["Cookie"] == "sessionid=private-test-cookie"
    assert "private-test-cookie" not in repr(requests_seen[0][1]["params"])


def test_tiktok_session_validation_rejects_expired_session(monkeypatch):
    class RejectedResponse:
        ok = True
        status_code = 200

        def json(self):
            return {"status_code": 8, "data": {}}

    monkeypatch.setattr(
        "app.streamer.tiktok_generator.requests.get",
        lambda *args, **kwargs: RejectedResponse(),
    )

    valid, message = TikTokStreamGenerator.validate_session("sessionid=private-test-cookie")

    assert valid is False
    assert message.startswith("SESSION_REJECTED:")


def test_tiktok_room_creation_stops_when_session_is_not_verified(monkeypatch):
    room_checks = []
    room_posts = []
    monkeypatch.setattr(
        TikTokStreamGenerator,
        "validate_session",
        classmethod(lambda cls, session_cookie: (False, "SESSION_REJECTED: session expired")),
    )
    monkeypatch.setattr(
        TikTokStreamGenerator,
        "get_current_room_info",
        classmethod(lambda cls, session_cookie: room_checks.append(session_cookie) or {}),
    )
    monkeypatch.setattr(
        "app.streamer.tiktok_generator.requests.post",
        lambda *args, **kwargs: room_posts.append((args, kwargs)),
    )

    success, _, message = TikTokStreamGenerator.create_room_and_get_key("sessionid=private-test-cookie")
    retry_success, _, retry_message = TikTokStreamGenerator.attempt_create_once(
        "sessionid=private-test-cookie"
    )

    assert success is False
    assert retry_success is False
    assert message.startswith("SESSION_REJECTED:")
    assert retry_message.startswith("SESSION_REJECTED:")
    assert room_checks == []
    assert room_posts == []


def test_tiktok_room_create_passes_event_id(monkeypatch):
    payloads = []
    _allow_tiktok_session(monkeypatch)

    monkeypatch.setattr(
        TikTokStreamGenerator,
        "get_current_room_info",
        classmethod(lambda cls, session_cookie: {"room_id": "", "live_status": 4, "is_live": False}),
    )
    monkeypatch.setattr(config, "reset_tiktok_session", lambda persist=True: None)
    monkeypatch.setattr(config, "update", lambda updates, persist=True: payloads.append(updates))

    class EventRoomResp:
        status_code = 200

        def json(self):
            return {
                "status_code": 0,
                "data": {
                    "id_str": "event-room",
                    "stream_url": {
                        "rtmp_push_url": "rtmp://push.example.com/stage/event-stream?x=1"
                    },
                },
            }

    def fake_post(url, **kwargs):
        payloads.append(kwargs["data"])
        return EventRoomResp()

    monkeypatch.setattr("app.streamer.tiktok_generator.requests.post", fake_post)

    ok, room, _ = TikTokStreamGenerator.create_room_and_get_key(
        "sessionid=abc123",
        event_id="https://www.tiktok.com/live/event/7693683878724272135?share=1",
    )

    assert ok is True
    assert room["room_id"] == "event-room"
    assert payloads[0]["event_id"] == "7693683878724272135"
    assert payloads[1]["tiktok_room_event_id"] == "7693683878724272135"


def test_tiktok_10037_retry_closes_old_room_before_recreating(monkeypatch):
    finish_calls = []
    post_calls = []
    _allow_tiktok_session(monkeypatch)

    monkeypatch.setattr(
        TikTokStreamGenerator,
        "clean_cookie_string",
        classmethod(lambda cls, raw: "sessionid=ae567d11bc7f225ace40e17e5ae63a4a"),
    )
    monkeypatch.setattr(
        TikTokStreamGenerator,
        "get_current_room_info",
        classmethod(lambda cls, session_cookie: {"room_id": "stale_room", "live_status": 1, "is_live": True}),
    )
    monkeypatch.setattr(
        TikTokStreamGenerator,
        "finish_room",
        classmethod(lambda cls, session_cookie, room_id="": finish_calls.append((session_cookie, room_id)) or (True, "closed")),
    )
    monkeypatch.setattr(
        config,
        "reset_tiktok_session",
        lambda persist=True: None,
    )
    monkeypatch.setattr(
        config,
        "update",
        lambda updates, persist=True: None,
    )

    responses = iter([
        type("R", (), {"json": lambda self: {"status_code": 10037}})(),
        type("R", (), {"json": lambda self: {"status_code": 0, "data": {"id_str": "new_room", "stream_url": {"rtmp_push_url": "rtmp://push.example.com/stage/stream-4321?x=1"}}}})(),
    ])

    def fake_post(*args, **kwargs):
        post_calls.append((args, kwargs))
        return next(responses)

    monkeypatch.setattr("app.streamer.tiktok_generator.requests.post", fake_post)

    ok, data, msg = TikTokStreamGenerator.create_room_and_get_key("sessionid=ae567d11bc7f225ace40e17e5ae63a4a", title="24/7 Test")

    assert ok is True
    assert finish_calls
    assert data["room_id"] == "new_room"


def test_tiktok_closed_room_is_not_repeatedly_finished_on_10037(monkeypatch):
    finish_calls = []
    post_calls = []
    sleep_calls = []
    _allow_tiktok_session(monkeypatch)

    monkeypatch.setattr(
        TikTokStreamGenerator,
        "clean_cookie_string",
        classmethod(lambda cls, raw: "sessionid=abc123"),
    )
    monkeypatch.setattr(
        TikTokStreamGenerator,
        "get_current_room_info",
        classmethod(lambda cls, session_cookie: {"room_id": "closed_room", "live_status": 4, "is_live": False}),
    )
    monkeypatch.setattr(
        TikTokStreamGenerator,
        "finish_room",
        classmethod(lambda cls, session_cookie, room_id="": finish_calls.append(room_id) or (True, "closed")),
    )
    monkeypatch.setattr(config, "tiktok_room_id", "")
    monkeypatch.setattr(config, "reset_tiktok_session", lambda persist=True: None)
    monkeypatch.setattr(config, "update", lambda updates, persist=True: None)
    monkeypatch.setattr("app.streamer.tiktok_generator.time.sleep", sleep_calls.append)

    class CooldownResp:
        def json(self):
            return {"status_code": 10037}

    def fake_post(*args, **kwargs):
        post_calls.append((args, kwargs))
        return CooldownResp()

    monkeypatch.setattr("app.streamer.tiktok_generator.requests.post", fake_post)

    ok, _, msg = TikTokStreamGenerator.create_room_and_get_key("sessionid=abc123")

    assert ok is False
    assert len(post_calls) == 4
    assert finish_calls == []
    assert sleep_calls == [5.0, 15.0, 30.0]
    assert "10037" in msg


def test_tiktok_10037_exhausted_retries_returns_accurate_guidance(monkeypatch):
    post_calls = []
    sleep_calls = []
    _allow_tiktok_session(monkeypatch)

    monkeypatch.setattr(
        TikTokStreamGenerator,
        "clean_cookie_string",
        classmethod(lambda cls, raw: "sessionid=abc123"),
    )
    monkeypatch.setattr(
        TikTokStreamGenerator,
        "get_current_room_info",
        classmethod(lambda cls, session_cookie: {"room_id": "", "live_status": -1, "is_live": False}),
    )
    monkeypatch.setattr(config, "tiktok_room_id", "")
    monkeypatch.setattr(TikTokStreamGenerator, "finish_room", classmethod(lambda cls, *args: (True, "closed")))
    monkeypatch.setattr(config, "reset_tiktok_session", lambda persist=True: None)
    monkeypatch.setattr(config, "update", lambda updates, persist=True: None)
    monkeypatch.setattr("app.streamer.tiktok_generator.time.sleep", sleep_calls.append)

    class CooldownResp:
        def json(self):
            return {"status_code": 10037}

    def fake_post(*args, **kwargs):
        post_calls.append((args, kwargs))
        return CooldownResp()

    monkeypatch.setattr("app.streamer.tiktok_generator.requests.post", fake_post)

    ok, _, msg = TikTokStreamGenerator.create_room_and_get_key("sessionid=abc123")

    assert ok is False
    assert len(post_calls) == 4
    assert sleep_calls == [5.0, 15.0, 30.0]
    assert "5, 15 ve 30 saniyelik" in msg
    assert "60 saniye bekleyin" in msg
    assert "lütfen 3 saniye sonra tekrar deneyiniz" not in msg


def test_tiktok_background_retry_continues_until_room_is_created(monkeypatch):
    from app.streamer.tiktok_generator import tiktok_generator

    monkeypatch.setattr(config, "tiktok_enabled", True)
    monkeypatch.setattr(config, "tiktok_session_id", "sessionid=test")
    monkeypatch.setattr("app.streamer.ffmpeg.TIKTOK_AUTO_RETRY_DELAYS", (0,))

    attempts = []

    def create_room(session_cookie, title, event_id=None):
        attempts.append((session_cookie, title))
        if len(attempts) == 1:
            return False, {}, "TikTok API 10037"
        return True, {"room_id": "new-room"}, "OK"

    monkeypatch.setattr(tiktok_generator, "create_room_and_get_key", create_room)

    streamer = FFmpegStreamer()
    streamer.start_tiktok_auto_retry(initial_delay_sec=0)
    assert streamer._bg_retry_thread is not None
    streamer._bg_retry_thread.join(timeout=5)

    assert not streamer._bg_retry_thread.is_alive()
    assert len(attempts) == 2
    assert streamer.get_status_info()["tiktok_automation"] == {
        "active": False,
        "status": "ready",
        "attempts": 2,
        "retry_in_seconds": None,
        "last_error": None,
    }


def test_tiktok_background_retry_stops_after_session_rejection(monkeypatch):
    from app.streamer.tiktok_generator import tiktok_generator

    monkeypatch.setattr(config, "tiktok_enabled", True)
    monkeypatch.setattr(config, "tiktok_session_id", "sessionid=test")
    attempts = []
    monkeypatch.setattr(
        tiktok_generator,
        "create_room_and_get_key",
        lambda **kwargs: attempts.append(kwargs)
        or (False, {}, "SESSION_REJECTED: TikTok oturumu reddedildi."),
    )

    streamer = FFmpegStreamer()
    streamer.start_tiktok_auto_retry(initial_delay_sec=0)
    assert streamer._bg_retry_thread is not None
    streamer._bg_retry_thread.join(timeout=5)

    assert not streamer._bg_retry_thread.is_alive()
    assert len(attempts) == 1
    assert streamer.get_status_info()["tiktok_automation"] == {
        "active": False,
        "status": "error",
        "attempts": 1,
        "retry_in_seconds": None,
        "last_error": "TikTok oturumu reddedildi.",
    }


def test_tiktok_only_stream_waits_for_automatic_room_retry(monkeypatch):
    monkeypatch.setattr(config, "tiktok_enabled", True)
    monkeypatch.setattr(config, "tiktok_session_id", "sessionid=test")
    monkeypatch.setattr(
        "app.streamer.ffmpeg.tiktok_manager._last_session_unavailable",
        True,
    )
    monkeypatch.setattr(
        "app.streamer.ffmpeg.video_validator.resolve_path",
        lambda source: (True, source, ""),
    )
    monkeypatch.setattr(
        "app.streamer.ffmpeg.metadata_mutator.on_stream_start",
        lambda *args: None,
    )

    streamer = FFmpegStreamer()
    retry_requests = []
    monkeypatch.setattr(
        streamer,
        "start_tiktok_auto_retry",
        lambda **kwargs: retry_requests.append(kwargs),
    )

    def fail_without_destinations():
        tiktok_manager._last_session_unavailable = True
        raise ValueError("No streaming destinations enabled.")

    monkeypatch.setattr(streamer, "build_command", fail_without_destinations)

    assert streamer.start() is True
    assert streamer.status == "WAITING_TIKTOK"
    assert retry_requests == [{"start_stream_on_success": True, "initial_delay_sec": 30}]


def test_ffmpeg_restart_preserves_tiktok_room(monkeypatch):
    streamer = FFmpegStreamer()
    stop_options = []
    monkeypatch.setattr(streamer, "stop", lambda **kwargs: stop_options.append(kwargs) or True)
    monkeypatch.setattr(streamer, "start", lambda: True)
    monkeypatch.setattr("app.streamer.ffmpeg.time.sleep", lambda seconds: None)

    assert streamer.restart() is True
    assert stop_options == [{"preserve_tiktok_room": True}]


def test_tiktok_generate_key_queues_automatic_retry_for_cooldown(monkeypatch):
    from app import routes

    monkeypatch.setattr(
        routes.ffmpeg_streamer,
        "create_tiktok_room",
        lambda **kwargs: (False, {}, "TikTok API error 10037"),
    )
    monkeypatch.setattr(routes.config, "update", lambda updates, persist=True: None)
    retry_requests = []
    monkeypatch.setattr(
        routes.ffmpeg_streamer,
        "start_tiktok_auto_retry",
        lambda **kwargs: retry_requests.append(kwargs),
    )
    monkeypatch.setattr(routes.ffmpeg_streamer, "is_running", lambda: False)

    result = routes.generate_tiktok_key(
        routes.TikTokKeyGenRequest(
            session_id="sessionid=test",
            event_id="https://www.tiktok.com/live/event/7693683878724272135",
            title="Automation test",
            auto_apply=True,
            start_stream=False,
        )
    )

    assert result["success"] is True
    assert result["pending"] is True
    assert "arka planda" in result["message"]
    assert retry_requests == [{"start_stream_on_success": False, "initial_delay_sec": 30}]


def test_tiktok_background_success_starts_deferred_stream(monkeypatch):
    from app.streamer.tiktok_generator import tiktok_generator
    from app.streamer.recovery import watchdog

    monkeypatch.setattr(config, "tiktok_enabled", True)
    monkeypatch.setattr(config, "tiktok_session_id", "sessionid=test")
    monkeypatch.setattr(tiktok_generator, "create_room_and_get_key", lambda **kwargs: (True, {"room_id": "ready"}, "OK"))
    monkeypatch.setattr(watchdog, "request_start", lambda: True)

    streamer = FFmpegStreamer()
    streamer.start_tiktok_auto_retry(start_stream_on_success=True, initial_delay_sec=0)
    assert streamer._bg_retry_thread is not None
    streamer._bg_retry_thread.join(timeout=5)

    assert not streamer._bg_retry_thread.is_alive()
    assert streamer.get_status_info()["tiktok_automation"]["status"] == "ready"
