"""Tor-Style Multi-Layer Onion Encryption API Router.

Exposes endpoints for:
  - 3-Hop Onion Circuits & Wrappers
  - Perfect Forward Secrecy (PFS) Ephemeral ECDH (X25519)
  - One-Time Nonce Self-Destructing Streaming Tickets
  - Honeypot Decoy Traps for Scrapers and Bots
  - Steganographic Polyglot PNG/WebP Transport (DPI Bypass)
  - Distributed WebRTC Peer-to-Peer Onion Relay Mesh
"""

from __future__ import annotations

import base64
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from app.onion_crypto import (
    HoneypotDecoyEngine,
    OnionCircuit,
    OnionCryptoEngine,
    P2PSwarmCoordinator,
    PFSKeyExchange,
    PFSSessionManager,
    StegoTransport,
    create_stream_onion_ticket,
    get_or_create_circuit,
    resolve_stream_onion_ticket,
)

router = APIRouter(prefix="/api/onion", tags=["Onion Routing & Cryptography"])


class WrapPayloadRequest(BaseModel):
    payload: Dict[str, Any]
    circuit_id: Optional[str] = "default-hotlink-circuit"
    extra_entropy: Optional[int] = 16


class PeelPayloadRequest(BaseModel):
    onion_token: str
    circuit_id: Optional[str] = "default-hotlink-circuit"
    consume_one_time: Optional[bool] = False


class PFSExchangeRequest(BaseModel):
    client_public_key_b64: str
    epoch: Optional[int] = None


class P2PJoinRequest(BaseModel):
    video_id: str
    peer_id: str


class P2PSignalRequest(BaseModel):
    from_peer: str
    to_peer: str
    signal_data: Dict[str, Any]


class StegoExtractRequest(BaseModel):
    png_base64: str


# =========================================================================
# CORE 3-HOP ONION CIRCUIT & WRAP / PEEL
# =========================================================================

@router.post("/circuit")
def create_or_rotate_circuit(circuit_id: Optional[str] = None):
    """Establishes or rotates an ephemeral 3-hop Tor-style Onion Circuit."""
    circuit = OnionCircuit.create(circuit_id=circuit_id)
    return {
        "status": "success",
        "circuit_id": circuit.circuit_id,
        "protocol": "tor-onion.v3 (AES-256-GCM)",
        "hops": [
            {"hop": 1, "role": "Guard / Entry Node", "algorithm": "AES-256-GCM"},
            {"hop": 2, "role": "Middle Relay Node", "algorithm": "AES-256-GCM"},
            {"hop": 3, "role": "Exit Node", "algorithm": "AES-256-GCM"},
        ],
        "created_at": circuit.created_at,
        "ttl_seconds": circuit.ttl_seconds,
    }


@router.post("/wrap")
def wrap_onion_payload(req: WrapPayloadRequest):
    """Encrypts an arbitrary payload into a 3-layer onion packet."""
    circuit = get_or_create_circuit(req.circuit_id)
    token = OnionCryptoEngine.wrap_onion(req.payload, circuit, extra_entropy_bytes=req.extra_entropy or 16)
    return {
        "status": "success",
        "circuit_id": circuit.circuit_id,
        "layers": 3,
        "onion_token": token,
    }


@router.post("/peel")
def peel_onion_payload(req: PeelPayloadRequest):
    """Peels all 3 layers of an onion packet and returns decrypted payload + audit log."""
    circuit = get_or_create_circuit(req.circuit_id)
    try:
        decrypted, audit_hops = OnionCryptoEngine.peel_onion(
            req.onion_token,
            circuit,
            consume_one_time=bool(req.consume_one_time),
        )
        return {
            "status": "success",
            "circuit_id": circuit.circuit_id,
            "peeled_hops": audit_hops,
            "payload": decrypted,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Onion peeling failed: {str(exc)}")


# =========================================================================
# 1. PERFECT FORWARD SECRECY (PFS) & EPHEMERAL ECDH (X25519)
# =========================================================================

@router.get("/pfs/epoch")
def get_pfs_epoch_info():
    """Returns the current server PFS epoch ID and ephemeral X25519 public key."""
    epoch_id, _, pub_b64 = PFSSessionManager.get_or_create_epoch_key()
    return {
        "status": "success",
        "epoch_id": epoch_id,
        "algorithm": "X25519-ECDH + HKDF-SHA256",
        "server_ephemeral_public_key": pub_b64,
        "rotation_interval_seconds": PFSSessionManager.EPOCH_DURATION,
    }


@router.post("/pfs/exchange")
def perform_pfs_key_exchange(req: PFSExchangeRequest):
    """Derives a forward-secret 256-bit session key against client's ephemeral public key."""
    epoch_id, priv_key, server_pub_b64 = PFSSessionManager.get_or_create_epoch_key(req.epoch)
    try:
        shared_key = PFSKeyExchange.derive_shared_key(priv_key, req.client_public_key_b64)
        return {
            "status": "success",
            "epoch_id": epoch_id,
            "server_ephemeral_public_key": server_pub_b64,
            "session_key_derived": True,
            "key_length_bits": len(shared_key) * 8,
            "forward_secrecy": "PERFECT",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PFS exchange failed: {str(exc)}")


# =========================================================================
# 2. STREAMING TICKETS (ONE-TIME NONCE & HONEYPOT INTEGRATION)
# =========================================================================

@router.get("/ticket/{video_id}")
def generate_onion_stream_ticket(
    video_id: str,
    source_file: str = "movie.safetensors",
    circuit_id: str = "default-hotlink-circuit",
    one_time: bool = False,
):
    """Generates an onion-shielded stream ticket, optionally self-destructing on first play."""
    ticket = create_stream_onion_ticket(
        video_id,
        source_file=source_file,
        circuit_id=circuit_id,
        one_time=one_time,
    )
    return {
        "status": "success",
        "ticket": ticket,
        "stream_url": f"/api/onion/stream?ticket={ticket}",
        "one_time_self_destruct": one_time,
        "protocol": "tor-onion.v3",
    }


@router.get("/stream")
async def stream_via_onion_ticket(
    request: Request,
    ticket: str = Query(..., description="3-Layer Onion Encrypted Stream Ticket"),
    circuit_id: str = "default-hotlink-circuit",
):
    """Resolves an onion stream ticket across 3 hops, defending against scrapers with Honeypot Decoys."""
    user_agent = request.headers.get("user-agent", "")

    # Honeypot Trigger 1: Detected automated scraper / IDM / scraper tool
    if HoneypotDecoyEngine.is_scraper_user_agent(user_agent):
        decoy_bytes = HoneypotDecoyEngine.generate_decoy_stream_chunk(8192)
        return Response(
            content=decoy_bytes,
            media_type="video/mp4",
            headers={
                "X-Honeypot-Trap": "active",
                "Content-Range": "bytes 0-8191/8192",
                "Accept-Ranges": "bytes",
            },
        )

    # Resolve onion ticket
    try:
        resolved, hops = resolve_stream_onion_ticket(
            ticket,
            circuit_id=circuit_id,
            consume_one_time=True,
        )
    except Exception as exc:
        # Honeypot Trigger 2: If a forged/corrupted token was sent by an unauthorized probe
        err_msg = str(exc).lower()
        if "self-destructed" in err_msg:
            raise HTTPException(status_code=403, detail="Onion stream ticket has self-destructed (one-time nonce expired)")
        # Serve decoy noise to avoid leaking internal errors
        decoy_bytes = HoneypotDecoyEngine.generate_decoy_stream_chunk(4096)
        return Response(
            content=decoy_bytes,
            media_type="video/mp4",
            headers={
                "X-Honeypot-Decoy": "forged_ticket",
                "Content-Range": "bytes 0-4095/4096",
            },
        )

    video_id = resolved.get("video_id")
    source_file = resolved.get("source_file", "movie.safetensors")

    if not video_id:
        raise HTTPException(status_code=400, detail="Missing video_id in onion payload")

    from app import main
    return await main.stream_safetensors_video(
        tensor_name=video_id,
        source_file=source_file,
        request=request,
    )


# =========================================================================
# 3. STEGANOGRAPHIC TRANSPORT (STEGO-TRANSPORT PNG/WEBP)
# =========================================================================

@router.get("/stego/{video_id}.png")
def get_stego_onion_png(
    video_id: str,
    source_file: str = "movie.safetensors",
    circuit_id: str = "default-hotlink-circuit",
):
    """Encapsulates a 3-layer onion stream ticket inside a valid RFC 2083 PNG image (DPI bypass)."""
    ticket = create_stream_onion_ticket(video_id, source_file=source_file, circuit_id=circuit_id)
    png_bytes = StegoTransport.embed_in_png(ticket)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, private",
            "X-Stego-Container": "polyglot-png-v1",
        },
    )


@router.post("/stego/extract")
def extract_stego_payload(req: StegoExtractRequest):
    """Extracts wrapped onion token from an uploaded/provided PNG image base64."""
    try:
        raw_png = base64.b64decode(req.png_base64)
        extracted_bytes = StegoTransport.extract_from_png(raw_png)
        token = extracted_bytes.decode("utf-8")
        return {
            "status": "success",
            "extracted_onion_token": token,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Stego extraction failed: {str(exc)}")


# =========================================================================
# 4. WEBRTC P2P DISTRIBUTED ONION RELAY MESH
# =========================================================================

@router.post("/p2p/join")
def join_p2p_swarm(req: P2PJoinRequest):
    """Registers a client peer into the video's distributed WebRTC relay swarm."""
    peers = P2PSwarmCoordinator.join_swarm(req.video_id, req.peer_id)
    stats = P2PSwarmCoordinator.get_swarm_stats(req.video_id)
    return {
        "status": "success",
        "peer_id": req.peer_id,
        "swarm_peers": peers,
        "stats": stats,
    }


@router.post("/p2p/signal")
def send_p2p_signal(req: P2PSignalRequest):
    """Exchanges an onion-shielded WebRTC SDP offer/answer/ICE candidate between peers."""
    P2PSwarmCoordinator.send_signal(req.from_peer, req.to_peer, req.signal_data)
    return {"status": "success", "delivered": True}


@router.get("/p2p/messages/{peer_id}")
def poll_p2p_signals(peer_id: str):
    """Polls pending WebRTC signaling messages for a peer."""
    messages = P2PSwarmCoordinator.poll_signals(peer_id)
    return {"status": "success", "messages": messages}


@router.get("/p2p/swarm/{video_id}")
def get_p2p_swarm_stats(video_id: str):
    """Returns active peer count, relay health, and bandwidth savings for the video."""
    return P2PSwarmCoordinator.get_swarm_stats(video_id)


# =========================================================================
# STATUS & CRYPTOGRAPHIC TELEMETRY
# =========================================================================

@router.get("/status")
def onion_mesh_status():
    """Returns complete cryptographic telemetry of all active privacy engines."""
    epoch_id, _, pub_b64 = PFSSessionManager.get_or_create_epoch_key()
    return {
        "protocol": "Tor-Style Onion Multi-Layer Routing (v3)",
        "encryption": "AES-256-GCM + SHA-256 MAC",
        "pfs": {
            "enabled": True,
            "algorithm": "X25519-ECDH + HKDF-SHA256",
            "current_epoch": epoch_id,
            "public_key": pub_b64,
        },
        "honeypot_traps": {
            "active": True,
            "decoy_format": "Synthetic Binary MP4 Stream",
            "anti_scraper_detection": True,
        },
        "self_destructing_tickets": {
            "supported": True,
            "one_time_nonce_invalidation": True,
        },
        "stego_transport": {
            "supported": True,
            "containers": ["image/png (RFC 2083)", "image/webp (RIFF)"],
        },
        "p2p_onion_mesh": {
            "active": True,
            "relay_protocol": "WebRTC-DataChannel",
        },
        "layers": [
            {"layer": 1, "name": "Guard (Entry)", "purpose": "Anti-Replay & Transport Armor"},
            {"layer": 2, "name": "Middle Relay", "purpose": "Decoy Routing & Entropy Masking"},
            {"layer": 3, "name": "Exit Node", "purpose": "Payload Execution & Safe Storage Bridge"},
        ],
        "mesh_status": "ACTIVE_SHIELDED",
        "server_time": time.time(),
    }
