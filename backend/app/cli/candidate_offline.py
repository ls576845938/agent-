"""python -m backend.app.cli.candidate_offline --help

Thin HTTP client: the running backend owns all jobs, authentication, capability,
idempotency and persistence. No local runtime fallback, no password arguments.
"""
import argparse
import getpass
import json
import sys
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765", help="running local backend, no proxy or redirect")
    parser.add_argument("--key-stdin", action="store_true", help="read local Web management key from one stdin line, never echo/store")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list"); sub.add_parser("catalog"); sub.add_parser("capabilities")
    for name in ("status", "result", "stop", "resume"):
        p = sub.add_parser(name); p.add_argument("job_id")
        if name == "result": p.add_argument("--before", type=int, help="exclusive decision cursor for older receipt page")
        if name in {"stop", "resume"}:
            p.add_argument("--expected-revision", type=int, required=True); p.add_argument("--request-key", required=True)
    p = sub.add_parser("publish")
    p.add_argument("source_revision_id"); p.add_argument("--expected-revision", type=int, required=True)
    p.add_argument("--request-key", required=True)
    p = sub.add_parser("start")
    p.add_argument("registration_id"); p.add_argument("--content-digest", required=True)
    p.add_argument("--expected-revision", type=int, required=True); p.add_argument("--input-revision-id", required=True)
    p.add_argument("--input-digest", required=True); p.add_argument("--request-key", required=True)
    args = parser.parse_args(argv)
    url = urlsplit(args.url)
    if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}):
        parser.error("local backend base URL required")
    key = sys.stdin.readline().rstrip("\r\n") if args.key_stdin else getpass.getpass("Local Web management key: ")
    body = None
    if args.command == "start":
        from backend.app.api.candidate_offline import Start
        body = Start(**{k: getattr(args, k) for k in ("registration_id", "content_digest", "expected_revision", "input_revision_id", "input_digest")}).model_dump()
        path = "/jobs"
    elif args.command == "publish":
        from backend.app.api.candidate_offline import Publish
        body = Publish(source_revision_id=args.source_revision_id, expected_revision=args.expected_revision).model_dump()
        path = "/publish"
    elif args.command in {"stop", "resume", "status", "result"}:
        from quant_shared.strategy_delivery.offline_contract import require_job
        path = "/jobs/" + require_job(args.job_id)
        if args.command != "status": path += "/" + args.command
        if args.command == "result" and args.before is not None:
            if not 1 <= args.before <= 2147483647: parser.error("before cursor out of range")
            path += "?before=" + str(args.before)
        if args.command in {"stop", "resume"}: body = {"expected_revision": args.expected_revision}
    else: path = {"list": "/jobs", "catalog": "/catalog", "capabilities": "/capabilities"}[args.command]
    headers = {"X-API-Key": key, "Content-Type": "application/json"}
    if body is not None: headers["Idempotency-Key"] = args.request_key
    request = Request(args.url.rstrip("/") + "/api/candidate-offline" + path,
                      data=None if body is None else json.dumps(body).encode(), headers=headers)
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=30) as response:
            result = json.load(response)
        print(json.dumps(result, ensure_ascii=False))
        return 2 if (result.get("status") or result.get("job", {}).get("status")) in {"blocked", "interrupted"} else 0
    except HTTPError as exc:
        import re
        try: detail = json.load(exc).get("detail")
        except (ValueError, AttributeError): detail = None
        code = detail if isinstance(detail, str) and re.fullmatch(r"[a-z0-9_:,.-]{1,300}", detail) else "backend_rejected_command"
        print(json.dumps({"status": "blocked", "http_status": exc.code, "error": code}))
        return 2
    except (URLError, TimeoutError, ValueError):
        print(json.dumps({"status": "blocked", "error": "backend_unavailable_or_response_unknown", "retry": "same_request_key_only"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
