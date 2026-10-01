"""No real secrets, listeners or candidate writes; request-bound local authority."""
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from backend.app.api.candidate_delivery import build_candidate_delivery_router
from backend.app.api.candidate_offline import build_candidate_offline_router
from backend.app.services.candidate_offline_service import CandidateOfflineService
from backend.app.core.candidate_local_auth import verify_local_request
from quant_shared.strategy_delivery.models import DeliveryError

H = {"Host": "127.0.0.1:8765", "X-QS-Candidate-Intent": "candidate-management"}
P = "/api/strategy-delivery/capabilities"

def request(headers=None, peer="127.0.0.1", path=P, method="GET"):
    return Request({"type":"http", "method":method, "scheme":"http", "path":path,
        "raw_path":path.encode(), "query_string":b"", "server":("127.0.0.1",8765),
        "client":(peer,1234), "headers":[(k.lower().encode(),v.encode()) for k,v in (headers or list(H.items()))]})

@pytest.mark.parametrize("peer", ["127.0.0.1","::1","::ffff:127.0.0.1"])
def test_local_intent_not_a_password(peer):
    assert verify_local_request(request(peer=peer))

@pytest.mark.parametrize("change", [
    {"peer":"192.168.1.4"}, {"peer":"testclient"}, {"peer":""},
    {"headers":[("Host","evil.test"),("X-QS-Candidate-Intent","candidate-management")]},
    {"headers":[*H.items(),("Host","localhost:8765")]},
    {"headers":[*H.items(),("Origin","null")]},
    {"headers":[*H.items(),("Origin","http://evil.test")]},
    {"headers":[*H.items(),("Origin","http://127.0.0.1:3000@evil.test")]},
    {"headers":[*H.items(),("Origin","http://127.0.0.1:3000"),("Origin","http://evil.test")]},
    {"headers":[*H.items(),("Sec-Fetch-Site","cross-site")]},
    {"headers":[*H.items(),("Sec-Fetch-Site","same-origin")]},
    {"headers":[("Host","127.0.0.1:8765")]},
    {"headers":[*H.items(),("X-Forwarded-For","127.0.0.1")]},
    {"headers":[*H.items(),("Forwarded","for=127.0.0.1")]},
    {"headers":[*H.items(),("X-QS-Candidate-Intent","candidate-management")]},
    {"headers":[*H.items(),("Origin","http://127.0.0.1:3000\r\nfake")]},
    {"path":"/api/research/btc/demo-paper/start","method":"POST"},
    {"path":"/api/strategy-delivery/packages/latest"},
    {"path":"/api/strategy-delivery/%63apabilities"},
    {"path":"/api//strategy-delivery/capabilities"},
])
def test_bad_request_rejected(change):
    with pytest.raises(Exception) as exc: verify_local_request(request(**change))
    assert getattr(exc.value,"status_code",None)==403

def test_browser_origin_and_get_referer_rules():
    browser = [*H.items(),("Sec-Fetch-Site","same-origin"),("Sec-Fetch-Mode","cors"),("Sec-Fetch-Dest","empty")]
    assert verify_local_request(request(headers=[*browser,("Origin","http://127.0.0.1:3000")]))
    assert verify_local_request(request(headers=[*browser,("Referer","http://127.0.0.1:3000/research")]))
    with pytest.raises(Exception):
        verify_local_request(request(headers=[*browser,("Referer","http://127.0.0.1:3000/research")],
                                     path="/api/strategy-delivery/packages",method="POST"))

def app_client(service=None, mode="local_no_password", enabled=True, profile="candidate_management", peer="127.0.0.1"):
    if service is None:
        service = SimpleNamespace(list=lambda: [], accounts=SimpleNamespace(list=lambda:[]))
    app=FastAPI()
    app.include_router(build_candidate_delivery_router(service=service,enabled=enabled,
        operator="operator",management_key="",auth_mode=mode,profile=profile),prefix="/api")
    return TestClient(app, base_url="http://127.0.0.1:8765",client=(peer,1234),headers=H)

def test_capabilities_and_records_without_key_never_command():
    service=SimpleNamespace(list=lambda: [], accounts=SimpleNamespace(list=lambda:[]),
        create=lambda *_a,**_k: pytest.fail("GET must not create"))
    web=app_client(service)
    value=web.get(P).json()
    assert value["auth_mode"]=="local_no_password" and value["commands_enabled"]
    assert not any(value["permissions"].values())
    assert web.get("/api/strategy-delivery/packages").json()=={"records":[], "permissions":value["permissions"]}

@pytest.mark.parametrize("profile,enabled", [("research_readonly",False),("demo_quasi_live",True),("promotion_strict",True)])
def test_local_mode_never_opens_other_profiles(profile,enabled):
    web=app_client(profile=profile,enabled=enabled)
    assert web.post("/api/strategy-delivery/packages",json={}).status_code==423

def test_offline_context_does_not_relax_enablement_or_accept_string():
    service=CandidateOfflineService(SimpleNamespace(head="a"*40),None,None,None,
        profile="candidate_management",enabled=False,operator="operator",management_key="",auth_mode="local_no_password")
    req=request(path="/api/candidate-offline/catalog")
    context=verify_local_request(req)
    assert service.authorize(context,write=False)=="operator"
    for invalid in (None,"","candidate-management",True,object()):
        with pytest.raises(DeliveryError): service.authorize(invalid,write=False)
    with pytest.raises(DeliveryError,match="commands_disabled"): service.authorize(context,write=True)
    app=FastAPI();app.include_router(build_candidate_offline_router(service),prefix="/api")
    web=TestClient(app,base_url="http://127.0.0.1:8765",client=("127.0.0.1",1234),headers=H)
    assert web.get("/api/candidate-offline/capabilities").json()["authenticated"]
    assert web.post("/api/candidate-offline/jobs",json={}).status_code==423


def test_valid_local_post_uses_configured_actor_without_key_or_real_write():
    calls=[]
    service=SimpleNamespace(create=lambda source,target,**kw: calls.append((source,target,kw)) or {"actor":kw["actor"]})
    web=app_client(service)
    headers={"Origin":"http://127.0.0.1:3000","Sec-Fetch-Site":"same-origin",
             "Sec-Fetch-Mode":"cors","Sec-Fetch-Dest":"empty","Idempotency-Key":"stable-1"}
    body={"source":{"kind":"qlib","run_id":"r","candidate_id":"c"},"target":"offline"}
    response=web.post("/api/strategy-delivery/packages",json=body,headers=headers)
    assert response.status_code==200 and response.json()["actor"]=="operator"
    assert calls[0][2]=={"key":"stable-1","actor":"operator"}
    calls.clear()
    for origin in ("null","http://evil.test"):
        assert web.post("/api/strategy-delivery/packages",json=body,headers={**headers,"Origin":origin}).status_code==403
    assert not calls

def test_old_key_mode_needs_no_new_headers_and_rejects_wrong_key():
    app=FastAPI()
    app.include_router(build_candidate_delivery_router(service=SimpleNamespace(list=lambda:[]),
        enabled=True,operator="operator",management_key="fixture-key"),prefix="/api")
    web=TestClient(app)
    assert web.get("/api/strategy-delivery/packages",headers={"X-API-Key":"fixture-key"}).status_code==200
    assert web.get("/api/strategy-delivery/packages",headers={"X-API-Key":"wrong"}).status_code==403

def test_wildcard_cors_cannot_authorize_cross_site_write():
    from fastapi.middleware.cors import CORSMiddleware
    web=app_client(SimpleNamespace(create=lambda *_a,**_k:pytest.fail("cross-site write")))
    web.app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
    headers={**H,"Origin":"http://evil.test","Idempotency-Key":"not-authorized"}
    assert web.post("/api/strategy-delivery/packages",headers=headers,json={}).status_code==403

@pytest.mark.parametrize("headers",[
    [*H.items(),("Sec-Fetch-Site","same-origin"),("Sec-Fetch-Mode","cors"),("Sec-Fetch-Dest","empty"),("Referer","http://evil.test")],
    [*H.items(),("Sec-Fetch-Site","same-origin"),("Sec-Fetch-Mode","navigate"),("Sec-Fetch-Dest","document"),("Origin","http://127.0.0.1:3000")],
    [*H.items(),("Sec-Fetch-Site","same-origin"),("Sec-Fetch-Mode","cors"),("Sec-Fetch-Dest","empty"),("Referer","http://[bad")],
])
def test_browser_partial_or_untrusted_context_rejected(headers):
    with pytest.raises(Exception) as exc: verify_local_request(request(headers=headers))
    assert getattr(exc.value,"status_code",None)==403
