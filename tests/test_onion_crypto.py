import base64
import time
import pytest
from app.onion_crypto import (
    HoneypotDecoyEngine,
    OnionCircuit,
    OnionCryptoEngine,
    OneTimeTicketManager,
    P2PSwarmCoordinator,
    PFSKeyExchange,
    PFSSessionManager,
    StegoTransport,
    create_stream_onion_ticket,
    get_or_create_circuit,
    resolve_stream_onion_ticket,
)


def test_onion_circuit_creation_and_expiration():
    circuit = OnionCircuit.create(ttl_seconds=1)
    assert len(circuit.guard_key) == 32
    assert len(circuit.relay_key) == 32
    assert len(circuit.exit_key) == 32
    assert not circuit.is_expired
    time.sleep(1.05)
    assert circuit.is_expired


def test_three_layer_onion_wrap_and_peel():
    circuit = OnionCircuit.create()
    test_payload = {
        "video_id": "vid_o71k91gsfs",
        "action": "p2p_stream",
        "node": "exit_01",
        "secret_param": "quantum_hash_42",
    }

    onion_token = OnionCryptoEngine.wrap_onion(test_payload, circuit)
    assert onion_token.startswith("tor-onion.v3:")
    assert circuit.circuit_id in onion_token

    decrypted, hops = OnionCryptoEngine.peel_onion(onion_token, circuit)
    assert decrypted["video_id"] == "vid_o71k91gsfs"
    assert decrypted["secret_param"] == "quantum_hash_42"
    assert hops == ["HOP_1_GUARD_UNLOCKED", "HOP_2_RELAY_UNLOCKED", "HOP_3_EXIT_UNLOCKED"]


def test_onion_tampering_fails_authentication():
    circuit = OnionCircuit.create()
    test_payload = {"msg": "confidential_onion_payload"}
    onion_token = OnionCryptoEngine.wrap_onion(test_payload, circuit)

    prefix, cid, payload_b64 = onion_token.split(":")
    corrupted_char = "A" if payload_b64[-5] != "A" else "B"
    corrupted_b64 = payload_b64[:-5] + corrupted_char + payload_b64[-4:]
    corrupted_token = f"{prefix}:{cid}:{corrupted_b64}"

    with pytest.raises(Exception):
        OnionCryptoEngine.peel_onion(corrupted_token, circuit)


def test_onion_stream_ticket_lifecycle():
    cid = "test-session-circuit"
    ticket = create_stream_onion_ticket("video_0000", source_file="movie.safetensors", circuit_id=cid)
    assert ticket.startswith("tor-onion.v3:test-session-circuit:")

    res, hops = resolve_stream_onion_ticket(ticket, circuit_id=cid)
    assert res["video_id"] == "video_0000"
    assert res["source_file"] == "movie.safetensors"
    assert len(hops) == 3


def test_anti_replay_expired_token():
    circuit = OnionCircuit.create()
    token = OnionCryptoEngine.wrap_onion({"test": 1}, circuit)
    time.sleep(0.05)
    with pytest.raises(ValueError, match="anti-replay"):
        OnionCryptoEngine.peel_onion(token, circuit, max_age_seconds=0)


def test_pfs_x25519_key_exchange():
    client_priv, client_pub_b64 = PFSKeyExchange.generate_keypair()
    server_epoch, server_priv, server_pub_b64 = PFSSessionManager.get_or_create_epoch_key()

    client_derived = PFSKeyExchange.derive_shared_key(client_priv, server_pub_b64)
    server_derived = PFSKeyExchange.derive_shared_key(server_priv, client_pub_b64)

    assert client_derived == server_derived
    assert len(client_derived) == 32


def test_one_time_self_destructing_ticket():
    cid = "test-self-destruct"
    ticket = create_stream_onion_ticket("video_secret", circuit_id=cid, one_time=True)

    # First peel with consume_one_time=True succeeds
    res1, _ = resolve_stream_onion_ticket(ticket, circuit_id=cid, consume_one_time=True)
    assert res1["video_id"] == "video_secret"

    # Second peel MUST fail with self-destruct error
    with pytest.raises(ValueError, match="self-destructed"):
        resolve_stream_onion_ticket(ticket, circuit_id=cid, consume_one_time=True)


def test_honeypot_decoy_detection_and_streaming():
    assert HoneypotDecoyEngine.is_scraper_user_agent("python-requests/2.31.0")
    assert HoneypotDecoyEngine.is_scraper_user_agent("curl/7.88.1")
    assert HoneypotDecoyEngine.is_scraper_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) HeadlessChrome/120.0.0.0")
    assert not HoneypotDecoyEngine.is_scraper_user_agent("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)")

    decoy_chunk = HoneypotDecoyEngine.generate_decoy_stream_chunk(512)
    assert len(decoy_chunk) == 512
    assert decoy_chunk.startswith(b"\x00\x00\x00\x18ftypmp42")


def test_stego_png_transport_and_extraction():
    sample_payload = "tor-onion.v3:circuit-xyz:sample_protected_packet"
    png_bytes = StegoTransport.embed_in_png(sample_payload)

    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in png_bytes
    assert b"onOn" in png_bytes
    assert png_bytes.endswith(b"IEND\xaeB`\x82")

    extracted = StegoTransport.extract_from_png(png_bytes)
    assert extracted.decode("utf-8") == sample_payload


def test_p2p_webrtc_swarm_and_signaling():
    video_id = "test_vid_p2p"
    peer_a = "peer_alpha"
    peer_b = "peer_beta"

    # Peer A joins
    peers_for_a = P2PSwarmCoordinator.join_swarm(video_id, peer_a)
    assert peer_a not in peers_for_a

    # Peer B joins and discovers Peer A
    peers_for_b = P2PSwarmCoordinator.join_swarm(video_id, peer_b)
    assert peer_a in peers_for_b

    # Peer A sends WebRTC signal to Peer B
    P2PSwarmCoordinator.send_signal(peer_a, peer_b, {"sdp": "offer_candidate_123"})
    signals_for_b = P2PSwarmCoordinator.poll_signals(peer_b)
    assert len(signals_for_b) == 1
    assert signals_for_b[0]["data"]["sdp"] == "offer_candidate_123"

    # Swarm stats
    stats = P2PSwarmCoordinator.get_swarm_stats(video_id)
    assert stats["active_relays"] == 2


def test_onion_api_endpoints():
    from starlette.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # 1. Status with all 5 privacy features
    res = client.get("/api/onion/status")
    assert res.status_code == 200
    data = res.json()
    assert data["mesh_status"] == "ACTIVE_SHIELDED"
    assert data["pfs"]["enabled"] is True
    assert data["honeypot_traps"]["active"] is True
    assert data["self_destructing_tickets"]["supported"] is True
    assert data["stego_transport"]["supported"] is True
    assert data["p2p_onion_mesh"]["active"] is True

    # 2. Circuit creation
    res = client.post("/api/onion/circuit?circuit_id=test-api-circ")
    assert res.status_code == 200
    cdata = res.json()
    assert cdata["circuit_id"] == "test-api-circ"

    # 3. PFS Endpoint Exchange
    epoch_res = client.get("/api/onion/pfs/epoch")
    assert epoch_res.status_code == 200
    _, client_pub = PFSKeyExchange.generate_keypair()
    ex_res = client.post("/api/onion/pfs/exchange", json={"client_public_key_b64": client_pub})
    assert ex_res.status_code == 200
    assert ex_res.json()["forward_secrecy"] == "PERFECT"

    # 4. Stego PNG Ticket Generation & Extraction
    stego_res = client.get("/api/onion/stego/vid_stego_test.png")
    assert stego_res.status_code == 200
    assert stego_res.headers["content-type"] == "image/png"
    assert stego_res.content.startswith(b"\x89PNG\r\n\x1a\n")

    extract_res = client.post("/api/onion/stego/extract", json={
        "png_base64": base64.b64encode(stego_res.content).decode("ascii")
    })
    assert extract_res.status_code == 200
    assert "extracted_onion_token" in extract_res.json()

    # 5. One-time self-destructing ticket endpoint
    t_res = client.get("/api/onion/ticket/vid_456?circuit_id=test-api-circ&one_time=true")
    assert t_res.status_code == 200
    assert t_res.json()["one_time_self_destruct"] is True

    # 6. Honeypot Decoy Trap for scrapers
    honeypot_stream = client.get(
        t_res.json()["stream_url"],
        headers={"User-Agent": "python-requests/2.31.0"}
    )
    assert honeypot_stream.status_code == 200
    assert honeypot_stream.headers.get("x-honeypot-trap") == "active"
    assert honeypot_stream.content.startswith(b"\x00\x00\x00\x18ftypmp42")

    # 7. P2P Swarm & Signaling API
    join_res = client.post("/api/onion/p2p/join", json={"video_id": "vid_456", "peer_id": "peer_api_1"})
    assert join_res.status_code == 200
    assert "stats" in join_res.json()
