---
title: Eshanio Video Platform
emoji: 🎬
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
---

# Eshanio Video Platform

When used as a separate Space, this Docker image serves the Eshanio web
interface, Node.js API, and internal Python byte-range video API from the same
public HTTPS origin. In the combined `hotlink` Space, its Node APIs are instead
proxied by the root FastAPI application.

## Temporary M3U shares

Open `/m3u-admin` on the running Node API to use the M3U management panel. Set
`M3U_ADMIN_API_KEY` on the API server first. For local development, copy
`backend_node/.env.example` to `backend_node/.env` and set a unique, long random
key. The panel sends the key only to the login endpoint, does not store it in
the browser, and uses a server-side session cookie that expires after eight
hours. For direct server-to-server API use, send the key in the
`x-m3u-api-key` header; never embed it in an Android app or public frontend.
M3U shares are unlisted bearer links: they do not appear in a public directory,
but anyone who gets the URL can use it. Set `PUBLIC_BASE_URL` to the public
HTTPS hostname used by your Space or reverse proxy. Production M3U links are
not created unless this hostname is configured; direct origin IP URLs are not
used as a fallback.

Management endpoints:

- `POST /api/playlist-shares` with `{ "videoIds": ["..."], "expiresInDays": 1 }`
- `GET /api/playlist-shares` to list links without exposing their tokens
- `DELETE /api/playlist-shares/:id` to revoke a link
- `GET /api/m3u/:token` for the M3U file
- `POST /api/app/activate` with `{ "code": "XXXX-XXXX-XXXX" }` for the Android app.
  Active codes return the playlist; unknown codes return `404 INVALID_CODE`, and
  expired or revoked codes return `410 CODE_EXPIRED` or `410 CODE_REVOKED`.
- `POST /api/m3u-admin/login`, `GET /api/m3u-admin/session`, and
  `POST /api/m3u-admin/logout` for panel sessions

`expiresInDays` accepts 1–30 days and defaults to 1. Share records use
`M3U_STORE_PATH` (the Docker image defaults to `/data/playlist-shares.json`);
attach persistent storage at `/data` if links must survive Space restarts.
Without persistent storage, generated shares may be lost when the Space
restarts or sleeps. Admin sessions are held in memory, so they are cleared when
the API restarts. Expiration/revocation disables fetching the M3U URL,
but video URLs already obtained from a playlist remain directly accessible
through the existing video API.

### Hiding the origin server IP

A domain name by itself does **not** hide an origin IP if its DNS `A`/`AAAA`
record points directly to that server. To keep the origin address out of public
DNS, use a reverse proxy/CDN or an outbound tunnel such as Cloudflare Tunnel,
point `PUBLIC_BASE_URL` at the public HTTPS hostname, and firewall the origin
so it only accepts traffic from the proxy/tunnel. Do not publish a direct
origin-IP DNS record. Verify the provider's bandwidth and video-streaming terms
before routing large media streams through it; this app's `/video/:id` links
also use the configured public hostname.
