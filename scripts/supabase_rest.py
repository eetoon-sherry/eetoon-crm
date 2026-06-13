"""Small Supabase REST client for GitHub Actions scripts."""

from __future__ import annotations

import json
import base64
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class SupabaseRestError(RuntimeError):
    pass


class SupabaseRestClient:
    def __init__(self, url: str, service_key: str):
        self.url = url.rstrip("/")
        self.service_key = service_key

    def request(self, method: str, path: str, data: Any = None, params: dict[str, Any] | None = None):
        url = f"{self.url}/rest/v1/{path}"
        if params:
            url += "?" + urllib.parse.urlencode({k: str(v) for k, v in params.items()})
        headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else []
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:1000]
            raise SupabaseRestError(f"Supabase REST {method} {path} failed: HTTP {exc.code} {detail}") from exc
        except Exception as exc:
            raise SupabaseRestError(f"Supabase REST {method} {path} failed: {exc}") from exc

    def health_check(self) -> None:
        if not self._looks_like_service_role_key():
            raise SupabaseRestError("SUPABASE_SERVICE_KEY must be a Supabase service_role JWT, not the publishable/anon key.")
        rows = self.request("GET", "settings", params={"select": "key", "limit": "1"})
        if not rows:
            raise SupabaseRestError("Supabase REST returned no settings rows. Check service_role key permissions and project URL.")

    def _looks_like_service_role_key(self) -> bool:
        parts = self.service_key.split(".")
        if len(parts) != 3:
            return False
        try:
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
        except Exception:
            return False
        return decoded.get("role") == "service_role"
