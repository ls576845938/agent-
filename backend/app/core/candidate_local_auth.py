"""Candidate-only local request authority; intent is public, not a secret.

Local processes are trusted, not identified as a person. Never infer a local
peer from Host/Origin or forwarding headers. No authority for trading routes.
"""
from dataclasses import dataclass
from ipaddress import ip_address
import re
from urllib.parse import urlsplit
from fastapi import HTTPException, Request

MODE = "local_no_password"
INTENT = "candidate-management"
HOSTS = {"127.0.0.1:8765", "localhost:8765", "[::1]:8765"}
ORIGINS = {"http://" + host for host in HOSTS} | {
    "http://127.0.0.1:3000", "http://localhost:3000", "http://[::1]:3000"}
_PROOF = object()

@dataclass(frozen=True)
class _LocalContext:
    proof: object

def is_local_context(value):
    return isinstance(value, _LocalContext) and value.proof is _PROOF

def candidate_route(method, path):
    delivery = "/api/strategy-delivery"
    offline = "/api/candidate-offline"
    if method == "GET":
        return (path in {delivery + p for p in ("/capabilities", "/accounts", "/packages", "/catalog")}
            or re.fullmatch(delivery + r"/packages/delivery_[0-9a-f]{32}", path) is not None
            or re.fullmatch(delivery + r"/requests/[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", path) is not None
            or path in {offline + p for p in ("/capabilities", "/catalog", "/jobs")}
            or re.fullmatch(offline + r"/jobs/coff_[0-9a-f]{32}(?:/result)?", path) is not None)
    if method == "POST":
        return (path == delivery + "/packages"
            or re.fullmatch(delivery + r"/packages/delivery_[0-9a-f]{32}/(?:bind|review|register|revoke)", path) is not None
            or path in {offline + "/jobs", offline + "/publish"}
            or re.fullmatch(offline + r"/jobs/coff_[0-9a-f]{32}/(?:stop|resume)", path) is not None)
    return False

def verify_local_request(request: Request):
    def reject():
        raise HTTPException(403, "candidate_local_request_rejected")
    # Reject forwarding headers even if Uvicorn already rewrote client.
    # Vite independently validates its unmodified socket peer.
    try:
        address = ip_address(request.client.host if request.client else "")
    except ValueError:
        reject()
    if not (address.is_loopback or (getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_loopback)):
        reject()
    headers = {}
    for key, value in request.scope.get("headers", []):
        try:
            name, text = key.decode("ascii").lower(), value.decode("ascii")
        except UnicodeError:
            reject()
        if (name in headers or not re.fullmatch(r"[a-z0-9-]+", name)
            or any(ord(c) < 32 or ord(c) == 127 for c in text)
            or name == "forwarded" or name.startswith("x-forwarded-")):
            reject()
        headers[name] = text
    if headers.get("host") not in HOSTS or headers.get("x-qs-candidate-intent") != INTENT:
        reject()
    path = request.scope.get("path", "")
    raw_path = request.scope.get("raw_path", path.encode()).decode("ascii", errors="replace")
    if raw_path != path or not candidate_route(request.method, path):
        reject()
    origin = headers.get("origin")
    metadata = {k: v for k, v in headers.items() if k.startswith("sec-fetch-")}
    if metadata and (set(metadata) != {"sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest"}
        or metadata["sec-fetch-site"] != "same-origin"
        or metadata["sec-fetch-mode"] not in {"cors", "same-origin"}
        or metadata["sec-fetch-dest"] != "empty"):
        reject()
    if origin is not None:
        if origin not in ORIGINS:
            reject()
    elif metadata:
        # Same-origin fetch GET omits Origin. No exception for writes.
        try:
            ref = urlsplit(headers.get("referer", ""))
        except ValueError:
            reject()
        if (request.method != "GET" or ref.username is not None or ref.password is not None
            or ref.fragment or ref.scheme + "://" + ref.netloc not in ORIGINS):
            reject()
    elif "referer" in headers:
        reject()
    return _LocalContext(_PROOF)
