"""YouTube OAuth 2.0 refresh_token oluvchi (bir marta ishga tushiriladi).

Foydalanish:
    1. Google Cloud Console'da OAuth 2.0 Client ID yarating (Desktop app).
    2. `client_id` va `client_secret`ni shu skript ichiga (yoki `.env`ga
       `ZET_YOUTUBE_OAUTH_CLIENT_ID`, `ZET_YOUTUBE_OAUTH_CLIENT_SECRET`)
       kiriting.
    3. `uv run python scripts/youtube_oauth.py` — brauzer ochiladi
       (localhost:8765 orqali callback), YouTube kanalingizga kirib
       ruxsat berasiz.
    4. Console'da refresh_token chop etiladi — uni `.env`ga
       `ZET_YOUTUBE_OAUTH_REFRESH_TOKEN` sifatida saqlang.

Refresh token abadiy (Google policy o'zgarmaguncha), lekin agar app
'Testing' fazasida bo'lsa 7 kun keyin expire bo'ladi — 'In production'
holatiga o'tkazish shart. Consent screen'da 'Publish' tugmasi.

Skript minimal HTTP server (stdlib only) — hech qanday tashqi kutubxona
kerak emas.
"""

from __future__ import annotations

import http.server
import os
import secrets
import socketserver
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 — bu URL, parol emas
_REDIRECT_HOST = "localhost"
_REDIRECT_PORT = 8765
_REDIRECT_URI = f"http://{_REDIRECT_HOST}:{_REDIRECT_PORT}/callback"

_received_code: dict[str, str] = {}
_state_token = secrets.token_urlsafe(16)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        query = urllib.parse.parse_qs(parsed.query)
        if query.get("state", [""])[0] != _state_token:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"state mismatch - CSRF")
            return

        code = query.get("code", [""])[0]
        _received_code["value"] = code

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<h1>OK - brauzerni yopib console'ga qayting.</h1>")

    def log_message(self, *_args: object) -> None:
        pass  # jim


def main() -> int:
    client_id = os.environ.get("ZET_YOUTUBE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("ZET_YOUTUBE_OAUTH_CLIENT_SECRET")

    if not client_id or not client_secret:
        print(
            "XATO: ZET_YOUTUBE_OAUTH_CLIENT_ID va ZET_YOUTUBE_OAUTH_CLIENT_SECRET "
            "environment o'zgaruvchilariga o'rnatilishi kerak.",
            file=sys.stderr,
        )
        print("Ularni .env ga qo'shing yoki eksport qiling.", file=sys.stderr)
        return 1

    # Auth URL yaratish
    params = {
        "client_id": client_id,
        "redirect_uri": _REDIRECT_URI,
        "response_type": "code",
        "scope": _SCOPE,
        "access_type": "offline",
        "prompt": "consent",  # refresh_token'ni majburiy olish uchun
        "state": _state_token,
    }
    auth_url = f"{_AUTH_URL}?{urllib.parse.urlencode(params)}"

    # Local server
    server = socketserver.TCPServer((_REDIRECT_HOST, _REDIRECT_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"Brauzerni ochyapman: {auth_url}")
    webbrowser.open(auth_url)

    # 2 daqiqa kutish
    for _ in range(120):
        if "value" in _received_code:
            break
        threading.Event().wait(1)

    server.shutdown()

    code = _received_code.get("value")
    if not code:
        print("XATO: kod olinmadi (timeout). Qayta urinib ko'ring.", file=sys.stderr)
        return 2

    # Kodni token'ga almashtirish
    token_data = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": _REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode()

    request = urllib.request.Request(
        _TOKEN_URL,
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    import json as _json

    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 — bizning URL
        body = _json.loads(response.read().decode())

    refresh_token = body.get("refresh_token")
    access_token = body.get("access_token")

    if not refresh_token:
        print("XATO: refresh_token qaytmadi. Consent screen'da 'offline access' rad etilgan.")
        print(f"Javob: {body}", file=sys.stderr)
        return 3

    print()
    print("─" * 60)
    print("MUVAFFAQIYATLI!")
    print("─" * 60)
    print()
    print("Uni .env ga saqlang:")
    print()
    print(f"ZET_YOUTUBE_OAUTH_REFRESH_TOKEN={refresh_token}")
    print()
    print("(access_token vaqtinchalik, 1 soat — u har chaqiruvda yangilanadi.)")
    print(f"[debug] access_token: {access_token[:20]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
