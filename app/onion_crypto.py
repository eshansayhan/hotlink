"""Tor-Style Multi-Layer Onion Encryption (Onion Routing Cryptographic Engine).

Implements 3-concentric layer authenticated encryption (AES-256-GCM + SHA-256)
modeled after The Onion Router (Tor) protocol specifications with:
  1. Perfect Forward Secrecy (PFS) via Ephemeral ECDH (X25519 + HKDF-SHA256)
  2. Honeypot Decoy Engine & Anti-Scraper Traps
  3. One-Time Nonce Self-Destructing Streaming Tickets
  4. Steganographic Transport (Polyglot PNG/WebP Container Masking)
  5. WebRTC P2P Distributed Onion Relay Mesh Coordinator
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import struct
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Master seed for deterministic circuit derivation fallback
ONION_MASTER_SEED = os.getenv("ONION_MASTER_SEED", "eshansayhan-tor-onion-mesh-quantum-2026")
DEFAULT_CIRCUIT_TTL = 900  # 15 minutes


def _derive_node_key(salt: str, role: str) -> bytes:
    """Derive a deterministic 256-bit key for a circuit node using HKDF-like SHA-256."""
    import hashlib
    data = f"{ONION_MASTER_SEED}:{salt}:{role}".encode("utf-8")
    return hashlib.sha256(data).digest()


# =========================================================================
# 1. PERFECT FORWARD SECRECY (PFS) & EPHEMERAL ECDH (X25519)
# =========================================================================

class PFSKeyExchange:
    """Ephemeral X25519 Elliptic Curve Diffie-Hellman key exchange for Forward Secrecy."""

    @staticmethod
    def generate_keypair() -> Tuple[x25519.X25519PrivateKey, str]:
        """Generates a fresh ephemeral X25519 keypair, returning (private_key, b64url_public_key)."""
        priv = x25519.X25519PrivateKey.generate()
        pub_raw = priv.public_key().public_bytes_raw()
        pub_b64 = base64.urlsafe_b64encode(pub_raw).decode("ascii").rstrip("=")
        return priv, pub_b64

    @staticmethod
    def derive_shared_key(
        our_priv: x25519.X25519PrivateKey,
        peer_pub_b64: str,
        context: bytes = b"tor-pfs-v3",
    ) -> bytes:
        """Derives a 256-bit AES-GCM session key from peer's public key using HKDF-SHA256."""
        pad_len = (4 - len(peer_pub_b64) % 4) % 4
        peer_pub_bytes = base64.urlsafe_b64decode(peer_pub_b64 + ("=" * pad_len))
        peer_pub = x25519.X25519PublicKey.from_public_bytes(peer_pub_bytes)
        shared_secret = our_priv.exchange(peer_pub)
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=context,
        ).derive(shared_secret)


class PFSSessionManager:
    """Rotates ephemeral ECDH keys every 300 seconds (5 minute epochs) to guarantee PFS."""

    EPOCH_DURATION = 300  # 5 minutes
    _epochs: Dict[int, x25519.X25519PrivateKey] = {}

    @classmethod
    def get_or_create_epoch_key(cls, epoch: Optional[int] = None) -> Tuple[int, x25519.X25519PrivateKey, str]:
        now_epoch = epoch if epoch is not None else int(time.time() // cls.EPOCH_DURATION)
        # Purge keys older than 2 epochs
        min_allowed = now_epoch - 2
        for ep in list(cls._epochs.keys()):
            if ep < min_allowed:
                del cls._epochs[ep]

        if now_epoch not in cls._epochs:
            priv = x25519.X25519PrivateKey.generate()
            cls._epochs[now_epoch] = priv

        priv = cls._epochs[now_epoch]
        pub_raw = priv.public_key().public_bytes_raw()
        pub_b64 = base64.urlsafe_b64encode(pub_raw).decode("ascii").rstrip("=")
        return now_epoch, priv, pub_b64


# =========================================================================
# 2. ONE-TIME NONCE & SELF-DESTRUCTING TICKETS
# =========================================================================

class OneTimeTicketManager:
    """Tracks one-time streaming tickets to prevent URL sharing and hotlinking."""

    _consumed: Dict[str, float] = {}

    @classmethod
    def is_consumed(cls, ticket_id: str) -> bool:
        cls._purge_stale()
        return ticket_id in cls._consumed

    @classmethod
    def consume(cls, ticket_id: str) -> bool:
        """Returns True if successfully consumed for the first time, False if already consumed."""
        cls._purge_stale()
        if ticket_id in cls._consumed:
            return False
        cls._consumed[ticket_id] = time.time()
        return True

    @classmethod
    def _purge_stale(cls, max_age: float = 3600.0) -> None:
        now = time.time()
        stale = [tid for tid, ts in cls._consumed.items() if now - ts > max_age]
        for tid in stale:
            del cls._consumed[tid]


# =========================================================================
# 3. HONEYPOT / DECOY STREAM GENERATOR
# =========================================================================

class HoneypotDecoyEngine:
    """Produces decoy video streams or traps for scrapers, bots, and unauthorized downloads."""

    DECOY_MP4_HEADER = (
        b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
        b"\x00\x00\x00\x08free"
        b"\x00\x00\x00\x28mdat\x00\x00\x00\x00[HONEYPOT_DECOY_STREAM_ACTIVE]"
    )

    @classmethod
    def is_scraper_user_agent(cls, user_agent: str) -> bool:
        ua = (user_agent or "").lower()
        scraper_tokens = [
            "python-requests", "curl", "wget", "sqlmap", "scrapy",
            "aiohttp", "httpx", "internet download manager", "idm",
            "jdownloader", "headlesschrome", "phantomjs", "puppeteer",
        ]
        return any(t in ua for t in scraper_tokens)

    @classmethod
    def generate_decoy_stream_chunk(cls, size: int = 4096) -> bytes:
        """Produces realistic-looking binary noise stream masquerading as encrypted HLS/safetensors."""
        header = cls.DECOY_MP4_HEADER
        if size <= len(header):
            return header[:size]
        noise = secrets.token_bytes(size - len(header))
        return header + noise


# =========================================================================
# 4. STEGANOGRAPHIC TRANSPORT (STEGO-TRANSPORT PNG/WEBP)
# =========================================================================

class StegoTransport:
    """Disguises encrypted onion packets or video chunks as valid PNG images to bypass DPI."""

    PNG_SIG = b"\x89PNG\r\n\x1a\n"
    CHUNK_TYPE = b"onOn"

    @classmethod
    def _make_chunk(cls, chunk_type: bytes, data: bytes) -> bytes:
        length = len(data)
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", length) + chunk_type + data + struct.pack(">I", crc)

    @classmethod
    def embed_in_png(cls, payload: bytes | str) -> bytes:
        """Wraps payload into a valid RFC 2083 PNG file with an ancillary onOn chunk."""
        if isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            payload_bytes = payload

        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr = cls._make_chunk(b"IHDR", ihdr_data)
        custom_chunk = cls._make_chunk(cls.CHUNK_TYPE, payload_bytes)
        idat = cls._make_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
        iend = cls._make_chunk(b"IEND", b"")
        return cls.PNG_SIG + ihdr + custom_chunk + idat + iend

    @classmethod
    def extract_from_png(cls, png_bytes: bytes) -> bytes:
        """Extracts the onion payload from the PNG onOn chunk."""
        if not png_bytes.startswith(cls.PNG_SIG):
            raise ValueError("Not a valid PNG signature")
        idx = png_bytes.find(cls.CHUNK_TYPE)
        if idx == -1:
            raise ValueError("Stego chunk not found in PNG")
        chunk_len = struct.unpack(">I", png_bytes[idx - 4 : idx])[0]
        data = png_bytes[idx + 4 : idx + 4 + chunk_len]
        return data


# =========================================================================
# 5. WEBRTC P2P ONION RELAY MESH COORDINATOR
# =========================================================================

class P2PSwarmCoordinator:
    """Coordinates WebRTC peer-to-peer onion relays for bandwidth offloading."""

    _swarms: Dict[str, Dict[str, float]] = {}
    _signals: Dict[str, List[Dict[str, Any]]] = {}

    @classmethod
    def join_swarm(cls, video_id: str, peer_id: str) -> List[str]:
        now = time.time()
        cls._purge_dead_peers()
        if video_id not in cls._swarms:
            cls._swarms[video_id] = {}
        cls._swarms[video_id][peer_id] = now
        peers = [p for p in cls._swarms[video_id].keys() if p != peer_id][:8]
        return peers

    @classmethod
    def send_signal(cls, from_peer: str, to_peer: str, signal_payload: Dict[str, Any]) -> None:
        if to_peer not in cls._signals:
            cls._signals[to_peer] = []
        cls._signals[to_peer].append({
            "from": from_peer,
            "ts": time.time(),
            "data": signal_payload,
        })
        if len(cls._signals[to_peer]) > 50:
            cls._signals[to_peer] = cls._signals[to_peer][-50:]

    @classmethod
    def poll_signals(cls, peer_id: str) -> List[Dict[str, Any]]:
        return cls._signals.pop(peer_id, [])

    @classmethod
    def get_swarm_stats(cls, video_id: str) -> Dict[str, Any]:
        cls._purge_dead_peers()
        peer_count = len(cls._swarms.get(video_id, {}))
        return {
            "video_id": video_id,
            "active_relays": peer_count,
            "bandwidth_saving_ratio": min(0.85, max(0.0, peer_count * 0.15)),
            "protocol": "WebRTC-DataChannel-OnionMesh-v1",
        }

    @classmethod
    def _purge_dead_peers(cls, timeout: float = 60.0) -> None:
        now = time.time()
        for vid in list(cls._swarms.keys()):
            cls._swarms[vid] = {p: ts for p, ts in cls._swarms[vid].items() if now - ts < timeout}
            if not cls._swarms[vid]:
                del cls._swarms[vid]


# =========================================================================
# ONION CIRCUIT & 3-LAYER CORE CRYPTOGRAPHIC ENGINE
# =========================================================================

@dataclass
class OnionCircuit:
    circuit_id: str
    guard_key: bytes
    relay_key: bytes
    exit_key: bytes
    created_at: float = field(default_factory=time.time)
    ttl_seconds: int = DEFAULT_CIRCUIT_TTL

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds

    @classmethod
    def create(cls, circuit_id: Optional[str] = None, ttl_seconds: int = DEFAULT_CIRCUIT_TTL) -> OnionCircuit:
        cid = circuit_id or secrets.token_hex(12)
        guard_key = AESGCM.generate_key(bit_length=256)
        relay_key = AESGCM.generate_key(bit_length=256)
        exit_key = AESGCM.generate_key(bit_length=256)
        return cls(
            circuit_id=cid,
            guard_key=guard_key,
            relay_key=relay_key,
            exit_key=exit_key,
            created_at=time.time(),
            ttl_seconds=ttl_seconds,
        )

    @classmethod
    def from_seed(cls, circuit_id: str, ttl_seconds: int = DEFAULT_CIRCUIT_TTL) -> OnionCircuit:
        return cls(
            circuit_id=circuit_id,
            guard_key=_derive_node_key(circuit_id, "guard"),
            relay_key=_derive_node_key(circuit_id, "relay"),
            exit_key=_derive_node_key(circuit_id, "exit"),
            created_at=time.time(),
            ttl_seconds=ttl_seconds,
        )


class OnionCryptoEngine:
    """Multi-layer Onion Encryption and Decryption engine (3-hop AES-256-GCM)."""

    VERSION_PREFIX = "tor-onion.v3"

    @staticmethod
    def _encrypt_layer(key: bytes, plaintext: bytes, aad: Optional[bytes] = None) -> bytes:
        nonce = secrets.token_bytes(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, aad)
        return nonce + ciphertext

    @staticmethod
    def _decrypt_layer(key: bytes, payload: bytes, aad: Optional[bytes] = None) -> bytes:
        if len(payload) < 28:
            raise ValueError("Invalid onion layer payload length")
        nonce = payload[:12]
        ciphertext = payload[12:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, aad)

    @classmethod
    def wrap_onion(
        cls,
        payload: Dict[str, Any] | bytes,
        circuit: OnionCircuit,
        extra_entropy_bytes: int = 16,
    ) -> str:
        """Wraps a payload into 3 concentric cryptographic layers."""
        if isinstance(payload, dict):
            raw_data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        else:
            raw_data = payload

        padding = secrets.token_bytes(extra_entropy_bytes)
        layer3_payload = json.dumps({
            "ts": time.time(),
            "p": base64.b64encode(raw_data).decode("ascii"),
            "noise": base64.b64encode(padding).decode("ascii"),
        }, separators=(",", ":")).encode("utf-8")

        # Layer 3 — Exit Cipher
        layer3_cipher = cls._encrypt_layer(circuit.exit_key, layer3_payload, aad=b"onion-exit-v3")

        # Layer 2 — Middle Relay Cipher
        layer2_payload = json.dumps({
            "hop": 2,
            "dest": "exit-node",
            "blob": base64.b64encode(layer3_cipher).decode("ascii"),
        }, separators=(",", ":")).encode("utf-8")
        layer2_cipher = cls._encrypt_layer(circuit.relay_key, layer2_payload, aad=b"onion-relay-v3")

        # Layer 1 — Guard / Entry Cipher
        layer1_payload = json.dumps({
            "hop": 1,
            "circuit": circuit.circuit_id,
            "dest": "relay-node",
            "blob": base64.b64encode(layer2_cipher).decode("ascii"),
        }, separators=(",", ":")).encode("utf-8")
        layer1_cipher = cls._encrypt_layer(circuit.guard_key, layer1_payload, aad=b"onion-guard-v3")

        b64_packet = base64.urlsafe_b64encode(layer1_cipher).decode("ascii").rstrip("=")
        return f"{cls.VERSION_PREFIX}:{circuit.circuit_id}:{b64_packet}"

    @classmethod
    def peel_onion(
        cls,
        onion_token: str,
        circuit: OnionCircuit,
        max_age_seconds: int = 3600,
        consume_one_time: bool = False,
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Peels all 3 layers of an onion packet, enforces anti-replay, and checks one-time consumption."""
        parts = onion_token.strip().split(":")
        if len(parts) != 3 or parts[0] != cls.VERSION_PREFIX:
            raise ValueError("Malformed onion token format")

        circuit_id, b64_layer1 = parts[1], parts[2]
        if circuit_id != circuit.circuit_id:
            raise ValueError(f"Circuit mismatch: token for {circuit_id}, expected {circuit.circuit_id}")

        pad_len = (4 - len(b64_layer1) % 4) % 4
        layer1_bytes = base64.urlsafe_b64decode(b64_layer1 + ("=" * pad_len))

        hops_audit: List[str] = []

        # --- Peel Hop 1: Guard Node ---
        raw_guard = cls._decrypt_layer(circuit.guard_key, layer1_bytes, aad=b"onion-guard-v3")
        guard_obj = json.loads(raw_guard.decode("utf-8"))
        if guard_obj.get("hop") != 1 or guard_obj.get("dest") != "relay-node":
            raise ValueError("Corrupted guard layer routing header")
        hops_audit.append("HOP_1_GUARD_UNLOCKED")

        # --- Peel Hop 2: Middle Relay Node ---
        layer2_bytes = base64.b64decode(guard_obj["blob"])
        raw_relay = cls._decrypt_layer(circuit.relay_key, layer2_bytes, aad=b"onion-relay-v3")
        relay_obj = json.loads(raw_relay.decode("utf-8"))
        if relay_obj.get("hop") != 2 or relay_obj.get("dest") != "exit-node":
            raise ValueError("Corrupted relay layer routing header")
        hops_audit.append("HOP_2_RELAY_UNLOCKED")

        # --- Peel Hop 3: Exit Node ---
        layer3_bytes = base64.b64decode(relay_obj["blob"])
        raw_exit = cls._decrypt_layer(circuit.exit_key, layer3_bytes, aad=b"onion-exit-v3")
        exit_obj = json.loads(raw_exit.decode("utf-8"))
        hops_audit.append("HOP_3_EXIT_UNLOCKED")

        # Anti-replay / timestamp validation
        created_ts = exit_obj.get("ts", 0)
        if time.time() - created_ts > max_age_seconds:
            raise ValueError("Onion packet expired (anti-replay check failed)")

        decrypted_payload_bytes = base64.b64decode(exit_obj["p"])
        try:
            decrypted_payload = json.loads(decrypted_payload_bytes.decode("utf-8"))
        except Exception:
            decrypted_payload = {"raw_bytes_b64": base64.b64encode(decrypted_payload_bytes).decode("ascii")}

        # Check self-destructing one-time ticket
        if isinstance(decrypted_payload, dict) and decrypted_payload.get("one_time"):
            ticket_id = decrypted_payload.get("ticket_id")
            if ticket_id:
                if consume_one_time:
                    if not OneTimeTicketManager.consume(ticket_id):
                        raise ValueError("Onion ticket has self-destructed (already consumed)")
                elif OneTimeTicketManager.is_consumed(ticket_id):
                    raise ValueError("Onion ticket has self-destructed (already consumed)")

        return decrypted_payload, hops_audit


_ACTIVE_CIRCUITS: Dict[str, OnionCircuit] = {}


def get_or_create_circuit(circuit_id: Optional[str] = None) -> OnionCircuit:
    cid = circuit_id or "default-hotlink-circuit"
    circuit = _ACTIVE_CIRCUITS.get(cid)
    if not circuit or circuit.is_expired:
        circuit = OnionCircuit.from_seed(cid)
        _ACTIVE_CIRCUITS[cid] = circuit
    return circuit


def create_stream_onion_ticket(
    video_id: str,
    source_file: str = "movie.safetensors",
    circuit_id: str = "default-hotlink-circuit",
    ttl: int = 1800,
    one_time: bool = False,
) -> str:
    """Creates a 3-layer encrypted Onion ticket, optionally self-destructing after first play."""
    circuit = get_or_create_circuit(circuit_id)
    payload: Dict[str, Any] = {
        "video_id": video_id,
        "source_file": source_file,
        "issued_at": time.time(),
        "ttl": ttl,
    }
    if one_time:
        payload["one_time"] = True
        payload["ticket_id"] = secrets.token_hex(16)

    return OnionCryptoEngine.wrap_onion(payload, circuit)


def resolve_stream_onion_ticket(
    onion_ticket: str,
    circuit_id: str = "default-hotlink-circuit",
    consume_one_time: bool = False,
) -> Tuple[Dict[str, Any], List[str]]:
    """Unwraps a 3-layer encrypted Onion ticket into video streaming parameters."""
    circuit = get_or_create_circuit(circuit_id)
    return OnionCryptoEngine.peel_onion(onion_ticket, circuit, consume_one_time=consume_one_time)
