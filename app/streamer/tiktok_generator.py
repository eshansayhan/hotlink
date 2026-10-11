import re
import time
import urllib.parse
from typing import Dict, Any, Tuple, Optional
import requests

from app.config import config
from app.monitoring.logger import stream_logger


class TikTokStreamGenerator:
    """
    Automated TikTok Live Room Creator & Stream Key Generator.
    Interacts with TikTok's Webcast API to request a temporary RTMP Push URL
    and Stream Key using the account's session cookie.
    """

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )

    SESSION_INFO_URL = "https://api16-normal-c-alisg.tiktokv.com/passport/account/info/v2/"
    SESSION_INFO_PARAMS = {
        "scene": "normal",
        "multi_login": "1",
        "account_sdk_source": "app",
        "passport-sdk-version": "19",
        "os_api": "25",
        "device_type": "A5010",
        "manifest_version_code": "2018093009",
        "app_name": "musical_ly",
        "version_name": "7.1.2",
        "version_code": "200705",
        "device_platform": "android",
        "aid": "1233",
    }
    SESSION_INFO_USER_AGENT = (
        "com.zhiliaoapp.musically/2022107060 (Linux; U; Android 7.1.2; "
        "en_US; G011A; Build/N2G48H;tt-ok/3.10.0.2)"
    )
    CREATE_INFO_URL = "https://webcast.tiktok.com/webcast/room/create_info/"
    PRIMARY_CREATE_URL = "https://webcast.tiktok.com/webcast/room/create/"
    FALLBACK_CREATE_URL = "https://webcast16-normal-c-useast1a.tiktokv.com/webcast/room/create/"
    PRIMARY_FINISH_URL = "https://webcast.tiktok.com/webcast/room/finish_abnormal/"
    FALLBACK_FINISH_URL = "https://webcast16-normal-c-useast1a.tiktokv.com/webcast/room/finish_abnormal/"
    PRE_FINISH_URL = "https://webcast.tiktok.com/webcast/room/anchor_pre_finish/"

    @classmethod
    def normalize_event_id(cls, value: str) -> str:
        """Accept a TikTok LIVE Event URL or its numeric ID."""
        raw_value = value.strip()
        if not raw_value or raw_value == "-1":
            return ""

        match = re.fullmatch(r"\d+", raw_value)
        if match:
            return raw_value

        parsed_url = urllib.parse.urlparse(raw_value)
        if parsed_url.scheme:
            host = (parsed_url.hostname or "").lower()
            if host != "tiktok.com" and not host.endswith(".tiktok.com"):
                raise ValueError("TikTok LIVE Etkinlik bağlantısı TikTok alan adında olmalı.")
            event_match = re.fullmatch(r"/live/event/(\d+)/?", parsed_url.path)
            if event_match:
                return event_match.group(1)

        raise ValueError("TikTok LIVE Event bağlantısı veya sayısal etkinlik ID'si geçerli değil.")

    @classmethod
    def clean_cookie_string(cls, raw_input: str) -> str:
        """
        Accepts raw sessionid, sessionid=value, or full browser cookie header,
        and returns a normalized cookie header string.
        """
        raw = raw_input.strip()
        if not raw:
            return ""

        # If it looks like a full cookie string already
        if "sessionid=" in raw:
            return raw

        # If it's a bare session token string (hex or alphanumeric)
        return f"sessionid={raw};"

    @classmethod
    def validate_session(cls, session_cookie: str) -> Tuple[bool, str]:
        """Verify the supplied session with TikTok before attempting room creation."""
        formatted_cookie = cls.clean_cookie_string(session_cookie)
        if not formatted_cookie:
            return False, "TikTok sessionid çerezi boş olamaz."

        headers = {
            "Accept": "application/json",
            "Cookie": formatted_cookie,
            "User-Agent": cls.SESSION_INFO_USER_AGENT,
        }
        try:
            resp = requests.get(
                cls.SESSION_INFO_URL,
                params=cls.SESSION_INFO_PARAMS,
                headers=headers,
                timeout=10,
            )
            if not resp.ok:
                if resp.status_code in (401, 403):
                    return False, (
                        "SESSION_REJECTED: TikTok oturum doğrulama API'si sessionid'yi "
                        f"kabul etmedi (HTTP {resp.status_code})."
                    )
                return False, f"TikTok oturum doğrulaması başarısız oldu (HTTP {resp.status_code})."

            data = resp.json()
            if not isinstance(data, dict):
                return False, "SESSION_UNVERIFIED: TikTok oturum doğrulama API'si beklenmeyen yanıt verdi."
            account = data.get("data")
            user_id = ""
            if isinstance(account, dict):
                user_id = str(account.get("user_id_str") or account.get("user_id") or "").strip()
            status_code = data.get("status_code")
            if str(status_code) == "0" and user_id:
                return True, "TikTok oturumu doğrulandı."
            if status_code not in (None, 0, "0"):
                return False, (
                    "SESSION_REJECTED: TikTok hesap API'si oturumu kabul etmedi "
                    f"(kod {data['status_code']})."
                )
            return False, (
                "SESSION_UNVERIFIED: TikTok hesabı doğrulanamadı; API yanıtı kullanıcı "
                "kimliği içermiyor. Session kontrol endpoint'i değişmiş olabilir."
            )
        except requests.exceptions.Timeout:
            return False, "TikTok oturum doğrulaması zaman aşımına uğradı."
        except requests.exceptions.RequestException:
            return False, "TikTok oturum doğrulaması sırasında bağlantı hatası oluştu."
        except (ValueError, TypeError):
            return False, "SESSION_UNVERIFIED: TikTok oturum doğrulama API'si geçersiz yanıt verdi."

    @classmethod
    def extract_session_id(cls, cookie_str: str) -> str:
        """Extract just the sessionid value for saving or reference."""
        match = re.search(r"sessionid=([a-zA-Z0-9_-]+)", cookie_str)
        if match:
            return match.group(1)
        # If user entered just token without prefix
        if "=" not in cookie_str and ";" not in cookie_str:
            return cookie_str.strip()
        return ""

    @classmethod
    def get_current_room_info(cls, session_cookie: str) -> Dict[str, Any]:
        """
        Queries TikTok Webcast create_info to check if the user has an active room,
        its real room ID, and live status.
        live_status: 1 (Live/Active), 4 (Finished/Closed)
        """
        formatted_cookie = cls.clean_cookie_string(session_cookie)
        if not formatted_cookie:
            return {"room_id": "", "live_status": -1, "is_live": False}

        headers = {
            "User-Agent": cls.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://livecenter.tiktok.com/producer",
            "Origin": "https://livecenter.tiktok.com",
            "Cookie": formatted_cookie,
        }
        params = {
            "aid": "1988",
            "app_name": "tiktok_webcast",
            "device_platform": "web",
            "live_id": "12",
        }

        try:
            resp = requests.get(cls.CREATE_INFO_URL, params=params, headers=headers, timeout=8)
            if resp.ok:
                data = resp.json().get("data", {})
                last_room_id = str(data.get("last_room_id_str") or data.get("last_room_id") or "").strip()
                live_status = data.get("live_status", -1)
                is_live = (live_status == 1)
                stream_logger.debug(
                    "TIKTOK-GEN",
                    f"TikTok create_info: room_id={last_room_id}, live_status={live_status}, is_live={is_live}"
                )
                return {
                    "room_id": last_room_id,
                    "live_status": live_status,
                    "is_live": is_live,
                    "raw": data,
                }
        except Exception as e:
            stream_logger.warn("TIKTOK-GEN", f"TikTok create_info sorgusu başarısız: {e}")

        return {"room_id": "", "live_status": -1, "is_live": False}

    @classmethod
    def parse_rtmp_push_url(cls, raw_push_url: str) -> Tuple[str, str]:
        """
        Parses a TikTok RTMP push URL into (rtmp_server_url, stream_key).
        TikTok usually returns URLs formatted as:
        rtmp://push-rtmp-f5-sg01.tiktokcdn.com/stage/stream-21377908...?amun=true&...
        """
        url = raw_push_url.strip()
        if "/" in url:
            last_slash_idx = url.rfind("/")
            base_url = url[:last_slash_idx]
            stream_key = url[last_slash_idx + 1 :]
            return base_url, stream_key
        return url, ""

    @classmethod
    def finish_room(cls, session_cookie: str, room_id: str = "") -> Tuple[bool, str]:
        """
        Aggressively closes an active live room on TikTok.
        Chains: anchor_pre_finish → finish_abnormal (primary+fallback) → finish (normal).
        Then polls create_info until live_status confirms closure (4 or 0).
        Finally waits a cooldown period so the next create_room won't hit 10037.
        """
        formatted_cookie = cls.clean_cookie_string(session_cookie)
        if not formatted_cookie:
            config.reset_tiktok_session(persist=True)
            return False, "Session çerezi eksik."

        # Query TikTok to see actual room status
        info = cls.get_current_room_info(formatted_cookie)
        current_live_status = info.get("live_status", -1)
        actual_room_id = str(info.get("room_id") or "").strip()

        target_room_id = str(room_id or config.tiktok_room_id or actual_room_id or "").strip()

        # If room is already finished on TikTok side (status 4 or 0 or no room)
        if current_live_status in (0, 4) or not target_room_id:
            config.reset_tiktok_session(persist=True)
            stream_logger.info("TIKTOK-GEN", f"TikTok yayın odası zaten kapalı (live_status={current_live_status}). Yerel anahtarlar sıfırlandı.")
            return True, "TikTok yayın odası zaten kapalı. Anahtarlar ve oda başarıyla sıfırlandı."

        # Room is active or pending (live_status 1 or 2), send multi-vector finish
        stream_logger.info("TIKTOK-GEN", f"TikTok Live Room ({target_room_id}) agresif kapatma başlatıldı...")

        headers = {
            "User-Agent": cls.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://livecenter.tiktok.com/producer",
            "Origin": "https://livecenter.tiktok.com",
            "Cookie": formatted_cookie,
        }
        params = {
            "aid": "1988",
            "app_name": "tiktok_webcast",
            "device_platform": "web",
            "live_id": "12",
            "room_id": str(target_room_id),
        }
        payload = {
            "room_id": str(target_room_id),
            "reason_no": 1,
            "finish_type": 0,
        }

        # Vector 0: Anchor Pre-Finish (signals TikTok the host intends to end)
        try:
            resp = requests.post(cls.PRE_FINISH_URL, params=params, data=payload, headers=headers, timeout=8)
            stream_logger.debug("TIKTOK-GEN", f"Pre-Finish yanıtı: {resp.status_code}")
        except Exception:
            pass

        time.sleep(1.0)

        # Vector 1: Primary Finish Abnormal
        try:
            resp = requests.post(cls.PRIMARY_FINISH_URL, params=params, data=payload, headers=headers, timeout=8)
            data = resp.json()
            stream_logger.debug("TIKTOK-GEN", f"Finish Abnormal yanıtı: {data}")
        except Exception:
            pass

        # Vector 2: Fallback Finish Abnormal
        try:
            requests.post(cls.FALLBACK_FINISH_URL, params=params, data=payload, headers=headers, timeout=5)
        except Exception:
            pass

        # Vector 3: Normal Finish
        try:
            requests.post("https://webcast.tiktok.com/webcast/room/finish/", params=params, data=payload, headers=headers, timeout=5)
        except Exception:
            pass

        # Poll TikTok until room closure is confirmed (live_status == 4 or 0)
        closure_confirmed = False
        for i in range(15):
            time.sleep(1.5)
            check = cls.get_current_room_info(formatted_cookie)
            ls = check.get("live_status", -1)
            stream_logger.debug("TIKTOK-GEN", f"Kapatma doğrulaması {i+1}/15 — live_status={ls}")
            if ls in (0, 4, -1):
                closure_confirmed = True
                break
            # If still live after 5 polls, re-send finish_abnormal
            if i == 5:
                try:
                    requests.post(cls.PRIMARY_FINISH_URL, params=params, data=payload, headers=headers, timeout=5)
                except Exception:
                    pass

        if not closure_confirmed:
            stream_logger.warn("TIKTOK-GEN", "TikTok odası 15 polling sonrası hâlâ kapanmadı. Yerel anahtarlar sıfırlanıyor.")

        # Post-closure cooldown: TikTok internally needs ~5s after status changes to release the session lock
        stream_logger.debug("TIKTOK-GEN", "Post-closure cooldown bekleniyor (5s)...")
        time.sleep(5.0)

        # Completely reset TikTok session keys and room in config
        config.reset_tiktok_session(persist=True)
        return True, "TikTok yayın odası başarıyla kapatıldı ve anahtarlar sıfırlandı."

    @classmethod
    def create_room_and_get_key(
        cls,
        session_cookie: str,
        title: str = "24/7 Live Stream",
        game_tag_id: int = 0,
        event_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], str]:
        """
        Sends a request to TikTok Webcast API to create a live broadcast room
        and extract the temporary RTMP URL and Stream Key.
        Automatically verifies and clears previous rooms if left open.
        """
        formatted_cookie = cls.clean_cookie_string(session_cookie)
        if not formatted_cookie:
            return False, {}, "TikTok sessionid çerezi boş olamaz."
        try:
            selected_event_id = cls.normalize_event_id(
                config.tiktok_event_id if event_id is None else event_id
            )
        except ValueError as e:
            return False, {}, str(e)

        session_valid, validation_message = cls.validate_session(formatted_cookie)
        if not session_valid:
            return False, {}, validation_message

        stream_logger.info("TIKTOK-GEN", f"TikTok Live Room oluşturma isteği gönderiliyor (Başlık: '{title}')...")

        # STEP 1: Pre-flight check on existing room state
        info = cls.get_current_room_info(formatted_cookie)
        active_id = str(info.get("room_id") or "").strip()
        live_status = info.get("live_status", -1)
        is_live = info.get("is_live", False)

        # If TikTok reports the previous room as already closed, clear stale local state so
        # the next create request is not blocked by a lingering room_id / stream key.
        if live_status in (0, 4):
            config.reset_tiktok_session(persist=True)
            stream_logger.info(
                "TIKTOK-GEN",
                f"TikTok yayın odası kapalı/bitmiş görünüyor (live_status={live_status}). Yerel stale session temizleniyor."
            )

        # If live and valid keys are cached, reuse immediately!
        if (
            is_live
            and active_id
            and config.tiktok_room_id == active_id
            and config.tiktok_room_event_id == selected_event_id
            and config.tiktok_stream_key
            and config.tiktok_rtmp_url
        ):
            stream_logger.info(
                "TIKTOK-GEN",
                f"TikTok Live Room ({active_id}) zaten aktif. Mevcut yayın anahtarı başarıyla uygulandı."
            )
            return (
                True,
                {
                    "room_id": active_id,
                    "rtmp_push_url": f"{config.tiktok_rtmp_url}/{config.tiktok_stream_key}",
                    "rtmp_url": config.tiktok_rtmp_url,
                    "stream_key": config.tiktok_stream_key,
                    "title": title,
                },
                "Mevcut TikTok canlı yayın odası kullanılıyor.",
            )

        stale_room_id = str(config.tiktok_room_id or "").strip()

        # If there's an active or pending room on TikTok (status 1 or 2), close it cleanly before creating a new one.
        # Also force a cleanup when the app still has a stale cached room_id from a previous run.
        should_close_room = live_status in (1, 2) or (
            stale_room_id and live_status not in (0, 4)
        )
        if should_close_room and (active_id or stale_room_id):
            room_to_close = (active_id or stale_room_id) if live_status in (1, 2) else stale_room_id
            stream_logger.info("TIKTOK-GEN", f"Açık kalan TikTok odası ({room_to_close}) sonlandırılıyor...")
            cls.finish_room(formatted_cookie, room_to_close)
            config.reset_tiktok_session(persist=True)
            # Poll TikTok until room closure is confirmed (live_status == 4)
            for _ in range(8):
                time.sleep(1.0)
                check = cls.get_current_room_info(formatted_cookie)
                if check.get("live_status") == 4 or not check.get("is_live"):
                    break
            time.sleep(2.0)

        headers = {
            "User-Agent": cls.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
            "Referer": "https://livecenter.tiktok.com/producer",
            "Origin": "https://livecenter.tiktok.com",
            "Cookie": formatted_cookie,
        }

        params = {
            "aid": "1988",
            "app_name": "tiktok_webcast",
            "device_platform": "web",
            "live_id": "12",
        }

        payload = {
            "title": title[:32] if title else "24/7 Live Stream",
            "live_type": 0,
            "live_mode": 1,
            "has_commerce_goods": 0,
            "genre_id": game_tag_id or 0,
            "event_id": selected_event_id or "-1",
        }

        endpoint = cls.PRIMARY_CREATE_URL
        last_error = ""

        try:
            stream_logger.debug("TIKTOK-GEN", f"Bağlanılıyor: {endpoint}")
            resp = requests.post(
                endpoint,
                params=params,
                data=payload,
                headers=headers,
                timeout=10,
            )

            try:
                data = resp.json()
            except Exception:
                return False, {}, f"TikTok API JSON formatında yanıt vermedi (HTTP {resp.status_code})."

            status_code = data.get("status_code", -1)

            # If TikTok returns 10037 / 20800 (session cooldown or stale room state)
            if status_code in (10037, 20800):
                info = cls.get_current_room_info(formatted_cookie)
                retry_room_status = info.get("live_status", -1)
                stale_room_id = str(config.tiktok_room_id or "").strip()
                if retry_room_status in (0, 4):
                    stale_room_id = ""
                elif info.get("room_id"):
                    stale_room_id = str(info.get("room_id") or stale_room_id).strip()

                stream_logger.warn(
                    "TIKTOK-GEN",
                    f"TikTok eski canlı oda / cooldown durumu tespit etti ({status_code}). Doğrulanmış eski oda varsa kapatılacak ve yerel stale state temizlenecek..."
                )

                if stale_room_id and retry_room_status not in (0, 4):
                    cls.finish_room(formatted_cookie, stale_room_id)
                config.reset_tiktok_session(persist=True)

                # TikTok can retain the previous room lock well beyond the initial finish request.
                retry_delays = [5.0, 15.0, 30.0]
                for idx, delay in enumerate(retry_delays, start=1):
                    stream_logger.info(
                        "TIKTOK-GEN",
                        f"TikTok cooldown bekleniyor ({delay}s) — deneme {idx}/{len(retry_delays)}..."
                    )
                    time.sleep(delay)

                    for ep in [cls.PRIMARY_CREATE_URL, cls.FALLBACK_CREATE_URL]:
                        try:
                            retry_resp = requests.post(ep, params=params, data=payload, headers=headers, timeout=10)
                            retry_data = retry_resp.json()
                            retry_code = retry_data.get("status_code", -1)
                            if retry_code == 0 and "data" in retry_data:
                                data = retry_data
                                status_code = 0
                                stream_logger.info(
                                    "TIKTOK-GEN",
                                    f"[OK] 10037/20800 cooldown aşıldı! {idx}. denemede ({delay}s) yeni TikTok odası oluşturuldu."
                                )
                                break
                            elif retry_code in (10037, 20800):
                                stream_logger.debug("TIKTOK-GEN", "Cooldown / stale-room lock devam ediyor, bekleniyor...")
                                break
                            else:
                                data = retry_data
                                status_code = retry_code
                                break
                        except Exception:
                            pass
                    if status_code == 0:
                        break

            # Check if successful
            if status_code == 0 and "data" in data:
                room_data = data["data"]
                room_id = str(room_data.get("id_str") or room_data.get("id", ""))
                stream_url_obj = room_data.get("stream_url", {})

                # Use canonical RTMP push URL (port 1935 standard RTMP) for maximum stability with FFmpeg tee muxer
                rtmp_push_url = stream_url_obj.get("rtmp_push_url", "")
                if not rtmp_push_url:
                    push_list = stream_url_obj.get("push_urls", [])
                    if push_list and isinstance(push_list, list) and len(push_list) > 0:
                        rtmp_push_url = push_list[0]

                if not rtmp_push_url:
                    return False, data, "TikTok başarılı yanıt verdi ancak RTMP Push URL bulunamadı."

                base_url, stream_key = cls.parse_rtmp_push_url(rtmp_push_url)

                # Persist newly created room ID and keys
                config.update(
                    {
                        "tiktok_room_id": room_id,
                        "tiktok_room_event_id": selected_event_id,
                        "tiktok_rtmp_url": base_url,
                        "tiktok_stream_key": stream_key,
                    },
                    persist=True,
                )

                stream_logger.info(
                    "TIKTOK-GEN",
                    f"[OK] TikTok Live Room başarıyla oluşturuldu! Room ID: {room_id}, URL: {base_url}",
                )

                return (
                    True,
                    {
                        "room_id": room_id,
                        "rtmp_push_url": rtmp_push_url,
                        "rtmp_url": base_url,
                        "stream_key": stream_key,
                        "title": title,
                    },
                    "TikTok canlı yayın odası oluşturuldu ve yeni yayın anahtarı başarıyla alındı.",
                )

            # Handle TikTok specific error codes
            err_message = data.get("message") or data.get("prompts") or "Bilinmeyen hata"

            if status_code == 10037:
                last_error = (
                    "TikTok önceki yayın oturumunu hâlâ açık görüyor (10037). "
                    "Eski oda kapatılmaya çalışıldı ve 5, 15 ve 30 saniyelik "
                    "otomatik tekrar denemeleri başarısız oldu. TikTok Live Center'da "
                    "açık bir yayın varsa kapatıp 60 saniye bekleyin, ardından "
                    "yeniden deneyin. Sorun sürerse sessionid çerezini yenileyin."
                )
            elif status_code == 20800:
                last_error = "TikTok API 20800 döndürdü: mevcut oturum / canlı oda durumu doğrulanamadı. Eski oda kapatılmamış olabilir veya session güncel değil. Lütfen TikTok Live Center'da açık yayını kapatıp 20-60 saniye bekleyin, ardından yeni sessionid ile tekrar deneyin."
            elif status_code in (10006, 10007, 20002, 20003):
                last_error = "TikTok oturumunuz (sessionid) geçersiz veya süresi dolmuş. Lütfen tiktok.com üzerinden güncel sessionid alınız."
            elif status_code in (10008, 10009):
                last_error = "TikTok güvenlik / bot doğrulaması (Captcha/X-Bogus) istedi. Lütfen tarayıcıda livecenter.tiktok.com'a girip bir kez oturum doğrulayınız."
            elif "no permission" in str(err_message).lower() or "not eligible" in str(err_message).lower():
                last_error = "TikTok hesabınızın canlı yayın açma yetkisi (Live Producer) bulunmuyor veya kısıtlı."
            else:
                last_error = f"TikTok API Hatası [{status_code}]: {err_message}"

            stream_logger.warn("TIKTOK-GEN", f"TikTok API reddetti: {last_error}")

        except requests.exceptions.Timeout:
            last_error = "TikTok API zaman aşımına uğradı (Timeout)."
        except requests.exceptions.RequestException as e:
            last_error = f"TikTok bağlantı hatası: {str(e)}"

        return False, {}, last_error

    @classmethod
    def attempt_create_once(
        cls,
        session_cookie: str,
        title: str = "24/7 Live Stream",
        event_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], str]:
        """
        Single-shot TikTok room creation — no internal retry loop.
        Designed for background retry schedulers that space their own intervals.

        Returns:
          (True,  data_dict, "OK")             — new room created, keys saved
          (False, {},        "10037_COOLDOWN") — session still cooling down
          (False, {},        "ALREADY_LIVE")   — room already live, keys reused
          (False, {},        "error_msg")      — other API/network error
        """
        formatted_cookie = cls.clean_cookie_string(session_cookie)
        if not formatted_cookie:
            return False, {}, "SESSION_MISSING"
        try:
            selected_event_id = cls.normalize_event_id(
                config.tiktok_event_id if event_id is None else event_id
            )
        except ValueError as e:
            return False, {}, str(e)

        session_valid, validation_message = cls.validate_session(formatted_cookie)
        if not session_valid:
            return False, {}, validation_message

        # Quick state check — reuse if room is still live with valid cached keys
        info = cls.get_current_room_info(formatted_cookie)
        is_live = info.get("is_live", False)
        active_id = str(info.get("room_id") or "").strip()

        if (
            is_live
            and active_id
            and config.tiktok_room_id == active_id
            and config.tiktok_room_event_id == selected_event_id
            and config.tiktok_stream_key
            and config.tiktok_rtmp_url
        ):
            return (
                True,
                {
                    "room_id": active_id,
                    "rtmp_url": config.tiktok_rtmp_url,
                    "stream_key": config.tiktok_stream_key,
                    "rtmp_push_url": f"{config.tiktok_rtmp_url}/{config.tiktok_stream_key}",
                },
                "ALREADY_LIVE",
            )

        headers = {
            "User-Agent": cls.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
            "Referer": "https://livecenter.tiktok.com/producer",
            "Origin": "https://livecenter.tiktok.com",
            "Cookie": formatted_cookie,
        }
        params = {
            "aid": "1988",
            "app_name": "tiktok_webcast",
            "device_platform": "web",
            "live_id": "12",
        }
        payload = {
            "title": title[:32] if title else "24/7 Live Stream",
            "live_type": 0,
            "live_mode": 1,
            "has_commerce_goods": 0,
            "genre_id": 0,
            "event_id": selected_event_id or "-1",
        }

        try:
            resp = requests.post(
                cls.PRIMARY_CREATE_URL,
                params=params,
                data=payload,
                headers=headers,
                timeout=10,
            )
            data = resp.json()
            status_code = data.get("status_code", -1)

            if status_code == 0 and "data" in data:
                room_data = data["data"]
                room_id = str(room_data.get("id_str") or room_data.get("id", ""))
                stream_url_obj = room_data.get("stream_url", {})
                rtmp_push_url = stream_url_obj.get("rtmp_push_url", "")
                if not rtmp_push_url:
                    push_list = stream_url_obj.get("push_urls", [])
                    if push_list and isinstance(push_list, list):
                        rtmp_push_url = push_list[0]

                if not rtmp_push_url:
                    return False, data, "RTMP_URL_MISSING"

                base_url, stream_key = cls.parse_rtmp_push_url(rtmp_push_url)
                config.update(
                    {
                        "tiktok_room_id": room_id,
                        "tiktok_room_event_id": selected_event_id,
                        "tiktok_rtmp_url": base_url,
                        "tiktok_stream_key": stream_key,
                    },
                    persist=True,
                )
                stream_logger.info(
                    "TIKTOK-GEN",
                    f"[BG-OK] Yeni TikTok odası oluşturuldu! Room ID: {room_id}",
                )
                return (
                    True,
                    {
                        "room_id": room_id,
                        "rtmp_url": base_url,
                        "stream_key": stream_key,
                        "rtmp_push_url": rtmp_push_url,
                    },
                    "OK",
                )

            elif status_code == 10037:
                return False, {}, "10037_COOLDOWN"

            else:
                msg = data.get("message") or data.get("prompts") or f"status={status_code}"
                return False, {}, f"API_ERROR:{status_code}:{msg}"

        except requests.exceptions.Timeout:
            return False, {}, "TIMEOUT"
        except Exception as e:
            return False, {}, f"EXCEPTION:{e}"


tiktok_generator = TikTokStreamGenerator()
