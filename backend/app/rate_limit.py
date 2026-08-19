import ipaddress
from slowapi import Limiter
from slowapi.util import get_remote_address


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip())
        return True
    except ValueError:
        return False


def _rate_limit_key(request) -> str:
    """Key rate limits by the real client IP.

    Only the Cf-Connecting-Ip header set by Cloudflare is trusted, and only
    when the immediate peer is a local proxy — cloudflared connects to this
    origin via http://localhost:7680. External peers can spoof
    Cf-Connecting-Ip and X-Forwarded-For when they hit 0.0.0.0:7680
    directly, so those headers are never trusted for them; the peer address
    is used instead (unspoofable)."""
    peer = request.client.host if request.client is not None else None
    if peer in ("127.0.0.1", "::1"):
        cf_ip = request.headers.get("Cf-Connecting-Ip")
        if cf_ip and _is_ip(cf_ip):
            return cf_ip.strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key)
