"""Generic outbound-HTTP tool used by the API specialist."""
from __future__ import annotations

import httpx

_ALLOWED_SCHEMES = {"http", "https"}
_MAX_BODY_CHARS = 4000


def call_api(
    url: str,
    method: str = "GET",
    params: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
    timeout: float = 10.0,
) -> dict:
    scheme = url.split("://", 1)[0].lower() if "://" in url else ""
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"url scheme '{scheme}' is not allowed; use http(s)")

    with httpx.Client(timeout=timeout) as client:
        response = client.request(
            method.upper(), url, params=params, json=json_body, headers=headers
        )

    try:
        body: object = response.json()
    except ValueError:
        body = response.text[:_MAX_BODY_CHARS]

    return {
        "status_code": response.status_code,
        "ok": response.is_success,
        "body": body,
    }
