import json
import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app import access_store
from app.admin_service import _discord_action_components

discord_router = APIRouter()


def _verify_discord_interaction(raw_body: bytes, signature: str, timestamp: str) -> bool:
    public_key = os.getenv("DISCORD_PUBLIC_KEY", "").strip()
    if not public_key or not signature or not timestamp:
        return False
    try:
        key_bytes = bytes.fromhex(public_key)
        sig_bytes = bytes.fromhex(signature)
        msg_bytes = timestamp.encode("utf-8") + raw_body
    except (ValueError, TypeError):
        return False

    try:
        from nacl.signing import VerifyKey
        VerifyKey(key_bytes).verify(msg_bytes, sig_bytes)
        return True
    except ImportError:
        pass
    except Exception:
        return False

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub_key = Ed25519PublicKey.from_public_bytes(key_bytes)
        pub_key.verify(sig_bytes, msg_bytes)
        return True
    except Exception:
        return False


@discord_router.post("/api/discord/interactions")
async def handle_discord_interactions(request: Request):
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")
    body = await request.body()

    if not _verify_discord_interaction(body, signature, timestamp):
        raise HTTPException(status_code=401, detail="Geçersiz Discord imzası.")

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Geçersiz JSON verisi.")

    interaction_type = payload.get("type")
    # Type 1: PING (Discord verification handshake)
    if interaction_type == 1:
        return JSONResponse({"type": 1})

    # Type 3: MESSAGE_COMPONENT (Buton Tıklaması)
    if interaction_type == 3:
        custom_id = str(payload.get("data", {}).get("custom_id", "")).strip()
        member = payload.get("member")
        user = (member.get("user") if member else payload.get("user")) or {}
        user_id = str(user.get("id", "discord-user"))

        if custom_id == "btn_check_remaining_time":
            active_info = access_store.get_user_active_code(user_id)
            if active_info:
                remaining = active_info["remaining_seconds"]
                h = remaining // 3600
                m = (remaining % 3600) // 60
                time_str = f"{h} saat {m} dakika" if h > 0 else f"{m} dakika"
                status_note = " *(Cihazla eşleşti)*" if active_info["redeemed"] else " *(Henüz kullanılmadı)*"
                content = f"⏱️ **HFStream Erişim Durumunuz**\n🔑 Kodunuz: `{active_info['code']}`\n⏳ Kalan Süreniz: **{time_str}**{status_note}"
            else:
                content = "❌ Aktif bir erişim kodunuz bulunmamaktadır.\n`/kod` yazarak anında yeni bir kod alabilirsiniz."

            return JSONResponse({
                "type": 4,
                "data": {
                    "content": content,
                    "flags": 64,
                },
            })

        return JSONResponse({"type": 6})

    # Type 2: APPLICATION_COMMAND
    if interaction_type == 2:
        cmd_data = payload.get("data", {})
        cmd_name = cmd_data.get("name", "")
        member = payload.get("member")
        user = (member.get("user") if member else payload.get("user")) or {}
        user_id = str(user.get("id", "discord-webhook-user"))

        if cmd_name == "kod":
            channel_id = str(payload.get("channel_id", "")).strip()
            allowed_channel = os.getenv("DISCORD_CHANNEL_ID", "").strip()
            if allowed_channel.isdigit() and channel_id != allowed_channel:
                return JSONResponse({
                    "type": 4,
                    "data": {
                        "content": f"❌ Kod almak için lütfen yalnızca <#{allowed_channel}> kanalını kullanın.",
                        "flags": 64,
                    },
                })

            # Rol Kontrolü (Gerekli rol şartı)
            member_roles = [str(r) for r in (member.get("roles", []) if member else [])]
            required_role = os.getenv("DISCORD_REQUIRED_ROLE_ID", "").strip()
            if required_role.isdigit() and required_role not in member_roles:
                return JSONResponse({
                    "type": 4,
                    "data": {
                        "content": "❌ Kod alabilmek için gerekli sunucu rolüne sahip olmanız gerekmektedir.",
                        "flags": 64,
                    },
                })

            # VIP / Booster Rol Kontrolü
            vip_role = os.getenv("DISCORD_VIP_ROLE_ID", "").strip()
            custom_hours = None
            vip_tag = ""
            if vip_role.isdigit() and vip_role in member_roles:
                try:
                    custom_hours = int(os.getenv("DISCORD_VIP_HOURS", "72"))
                except ValueError:
                    custom_hours = 72
                vip_tag = f"\n⭐ *VIP / Booster üye olarak {custom_hours} saatlik ({custom_hours // 24} gün) kod tanımlandı!*"

            client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
            username = str(user.get("username", "") or user.get("global_name", "") or user_id)
            user_label = f"{username} ({user_id})" if username != user_id else user_id
            code = access_store.issue_code(
                user_id,
                custom_hours=custom_hours,
                note=f"VIP Discord: {user_label}" if custom_hours else f"Discord: {user_label}",
                ip_address=client_ip,
            )
            code_msg = (
                f"HFStream erişim kodun: {code}\n"
                f"Lütfen kodu uygulamadan aktifleştirin.{vip_tag}"
            )

            return JSONResponse({
                "type": 4,
                "data": {
                    "content": code_msg,
                    "flags": 64,
                    "components": _discord_action_components(),
                },
            })

        if cmd_name in ("bilgi", "kalan-sure", "kalansure", "surem", "sure"):
            active_info = access_store.get_user_active_code(user_id)
            if active_info:
                remaining = active_info["remaining_seconds"]
                h = remaining // 3600
                m = (remaining % 3600) // 60
                time_str = f"{h} saat {m} dakika" if h > 0 else f"{m} dakika"
                status_note = " *(Cihazla eşleşti)*" if active_info["redeemed"] else " *(Henüz kullanılmadı)*"
                content = f"Aktif Kodunuz: `{active_info['code']}` (Kalan Süre: {time_str}){status_note}"
            else:
                content = "Aktif bir erişim kodunuz bulunmamaktadır.\n`/kod` yazarak yeni bir kod alabilirsiniz."

            return JSONResponse({
                "type": 4,
                "data": {
                    "content": content,
                    "flags": 64,
                    "components": _discord_action_components(),
                },
            })

        return JSONResponse({
            "type": 4,
            "data": {
                "content": f"Bilinmeyen komut: {cmd_name}",
                "flags": 64,
            },
        })

    return JSONResponse({"type": 1})
