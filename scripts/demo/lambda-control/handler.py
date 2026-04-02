"""
Lambda handler for aasmaa Demo Control Panel.
Served via Lambda Function URL — no API Gateway needed.

Routes (all via query param ?action=...):
  GET  /                       → HTML control panel
  GET  /?action=status         → JSON service status
  POST /?action=start          → scale both ECS services to 1
  POST /?action=stop           → scale both ECS services to 0

Auth: every request must include ?token=<CONTROL_TOKEN env var>.
      Token is compared with hmac.compare_digest (constant-time).
"""

import hmac
import json
import os

import boto3
from botocore.exceptions import ClientError

# ── config ────────────────────────────────────────────────────────────────────
CLUSTER       = os.environ.get("ECS_CLUSTER", "aasmaa-demo-barebones-cluster")
ECS_SERVICES  = os.environ.get("ECS_SERVICES", "aasmaa-demo-barebones-backend|aasmaa-demo-barebones-frontend")
SERVICES      = [s.strip() for s in ECS_SERVICES.replace("|", ",").split(",") if s.strip()]
ECS_REGION    = os.environ.get("ECS_REGION") or os.environ.get("AWS_REGION", "ap-south-1")
CONTROL_TOKEN = os.environ.get("CONTROL_TOKEN", "")
DEMO_URL      = os.environ.get("DEMO_URL", "https://demo.aasmaa.ai")

# ── embedded HTML ─────────────────────────────────────────────────────────────
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>aasmaa Demo Control</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #0f1117; color: #e2e8f0;
      min-height: 100vh; display: flex; align-items: center; justify-content: center;
    }
    .container { width: 100%; max-width: 660px; padding: 28px 20px; }

    /* ── header ── */
    .header { text-align: center; margin-bottom: 32px; }
    .logo { font-size: 1.9rem; font-weight: 800; color: #fff; letter-spacing: -0.5px; }
    .logo span { color: #6366f1; }
    .subtitle { color: #64748b; margin-top: 6px; font-size: 0.88rem; }

    /* ── alert ── */
    .alert {
      background: #78350f22; border: 1px solid #92400e;
      border-radius: 8px; padding: 12px 16px;
      color: #fbbf24; font-size: 0.84rem; margin-bottom: 22px;
      display: none;
    }

    /* ── service cards ── */
    .cards { display: flex; flex-direction: column; gap: 10px; margin-bottom: 24px; }
    .card {
      background: #1a1d2e; border: 1px solid #252840;
      border-radius: 12px; padding: 16px 20px;
      display: flex; align-items: center; justify-content: space-between;
      transition: border-color 0.2s;
    }
    .card.running  { border-left: 3px solid #22c55e; }
    .card.stopped  { border-left: 3px solid #ef4444; }
    .card.starting { border-left: 3px solid #f59e0b; }
    .card-title  { font-weight: 600; font-size: 0.97rem; text-transform: capitalize; }
    .card-sub    { font-size: 0.75rem; color: #475569; margin-top: 2px; font-family: monospace; }
    .card-right  { display: flex; align-items: center; gap: 14px; }
    .card-counts { font-size: 0.78rem; color: #475569; text-align: right; }
    .card-counts b { color: #94a3b8; }

    /* ── badges ── */
    .badge {
      display: inline-flex; align-items: center; gap: 5px;
      padding: 3px 11px; border-radius: 20px;
      font-size: 0.73rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
    }
    .badge-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
    .badge-running  { background: #14532d33; color: #4ade80; border: 1px solid #15803d66; }
    .badge-running .badge-dot  { background: #4ade80; box-shadow: 0 0 6px #4ade8088; }
    .badge-stopped  { background: #450a0a33; color: #f87171; border: 1px solid #7f1d1d66; }
    .badge-stopped .badge-dot  { background: #f87171; }
    .badge-starting { background: #78350f33; color: #fbbf24; border: 1px solid #92400e66; }
    .badge-starting .badge-dot { background: #fbbf24; animation: blink 1s ease-in-out infinite; }
    .badge-unknown  { background: #1e293b; color: #64748b; border: 1px solid #2d3748; }
    .badge-unknown .badge-dot  { background: #475569; }
    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.25} }

    /* ── action buttons ── */
    .actions { display: flex; gap: 10px; margin-bottom: 18px; }
    .btn {
      flex: 1; padding: 11px 18px; border: none; border-radius: 8px;
      font-size: 0.9rem; font-weight: 600; cursor: pointer;
      transition: background 0.15s, opacity 0.15s;
      display: flex; align-items: center; justify-content: center; gap: 7px;
    }
    .btn:disabled { opacity: 0.38; cursor: not-allowed; }
    .btn-start   { background: #4f46e5; color: #fff; }
    .btn-start:hover:not(:disabled)   { background: #4338ca; }
    .btn-stop    { background: #dc2626; color: #fff; }
    .btn-stop:hover:not(:disabled)    { background: #b91c1c; }
    .btn-refresh { background: #1a1d2e; color: #94a3b8; border: 1px solid #252840; flex: 0; padding: 11px 16px; font-size: 1rem; }
    .btn-refresh:hover:not(:disabled) { border-color: #4f46e5; color: #e2e8f0; }

    /* ── log ── */
    .log-wrap { position: relative; }
    .log {
      background: #0d1117; border: 1px solid #1e2535;
      border-radius: 8px; padding: 12px 14px;
      font-family: 'SF Mono', 'Fira Code', 'Fira Mono', monospace;
      font-size: 0.77rem; color: #64748b;
      min-height: 56px; max-height: 130px; overflow-y: auto; line-height: 1.75;
    }
    .log .ok  { color: #4ade80; }
    .log .err { color: #f87171; }
    .log .info { color: #38bdf8; }
    .log .warn { color: #fbbf24; }

    /* ── demo link ── */
    .demo-link {
      text-align: center; margin-top: 18px;
      padding: 12px; background: #1a1d2e; border: 1px solid #252840; border-radius: 8px;
      font-size: 0.84rem; color: #64748b;
    }
    .demo-link a { color: #6366f1; text-decoration: none; font-weight: 600; }
    .demo-link a:hover { text-decoration: underline; }

    /* ── footer ── */
    .footer {
      display: flex; justify-content: space-between; align-items: center;
      margin-top: 14px; font-size: 0.73rem; color: #334155;
    }

    /* ── spinner ── */
    .spin {
      width: 13px; height: 13px;
      border: 2px solid rgba(255,255,255,.25); border-top-color: currentColor;
      border-radius: 50%; animation: spin .7s linear infinite; display: inline-block;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
<div class="container">

  <div class="header">
    <div class="logo"><span>aasmaa</span> demo control</div>
    <div class="subtitle">Start and stop ECS services before/after client demos</div>
  </div>

  <div class="alert" id="alert">
    &#9888;&nbsp; No token found in URL &mdash; actions are disabled.
    Share the full URL (including <code>?token=…</code>) with your team.
  </div>

  <div class="cards" id="cards">
    <div class="card">
      <div><div class="card-title">Loading&hellip;</div></div>
      <div class="card-right">
        <div class="badge badge-unknown"><div class="badge-dot"></div>—</div>
      </div>
    </div>
  </div>

  <div class="actions">
    <button class="btn btn-start"   id="btn-start"   onclick="doAction('start')" disabled>&#9654; Start Services</button>
    <button class="btn btn-stop"    id="btn-stop"    onclick="doAction('stop')"  disabled>&#9632; Stop Services</button>
    <button class="btn btn-refresh" id="btn-refresh" onclick="loadStatus()" title="Refresh">&#8635;</button>
  </div>

  <div class="log-wrap">
    <div class="log" id="log"><span>Requesting status&hellip;</span></div>
  </div>

  <div class="demo-link">
    Demo site &rarr; <a href="DEMO_URL_PLACEHOLDER" target="_blank" rel="noopener">DEMO_URL_PLACEHOLDER</a>
  </div>

  <div class="footer">
    <span>Auto-refreshes every 15 s</span>
    <span>Last updated: <span id="ts">—</span></span>
  </div>

</div>
<script>
(function () {
  const qs     = new URLSearchParams(location.search);
  const TOKEN  = qs.get('token') || '';
  const BASE   = location.origin + location.pathname;
  let busy = false;

  if (!TOKEN) document.getElementById('alert').style.display = 'block';

  /* ── logging ── */
  const logEl = document.getElementById('log');
  function log(msg, cls) {
    const t = new Date().toLocaleTimeString();
    logEl.innerHTML += '<span class="' + (cls||'') + '">[' + t + '] ' + msg + '</span><br>';
    logEl.scrollTop = logEl.scrollHeight;
  }
  logEl.innerHTML = '';

  /* ── status rendering ── */
  function serviceState(s) {
    if (s.desired === 0)                                            return 'stopped';
    if (s.running >= 1 && s.rolloutState === 'COMPLETED')          return 'running';
    return 'starting';
  }
  function stateLabel(st) {
    return {running:'Running', stopped:'Stopped', starting:'Starting'}[st] || 'Unknown';
  }
  function renderCards(services) {
    document.getElementById('cards').innerHTML = services.map(function(svc) {
      var state = serviceState(svc);
      var name  = svc.name.replace('aasmaa-','');
      return '<div class="card ' + state + '">'
        + '<div>'
        + '<div class="card-title">' + name.charAt(0).toUpperCase() + name.slice(1) + '</div>'
        + '<div class="card-sub">'  + svc.name + '</div>'
        + '</div>'
        + '<div class="card-right">'
        + '<div class="card-counts">desired <b>' + svc.desired + '</b><br>running <b>' + svc.running + '</b></div>'
        + '<div class="badge badge-' + state + '"><div class="badge-dot"></div>' + stateLabel(state) + '</div>'
        + '</div>'
        + '</div>';
    }).join('');
  }
  function renderUnknownCards() {
    renderCards([
      { name: 'aasmaa-backend', desired: 0, running: 0, pending: 0, rolloutState: 'UNKNOWN' },
      { name: 'aasmaa-frontend', desired: 0, running: 0, pending: 0, rolloutState: 'UNKNOWN' }
    ]);
  }
  function updateButtons(services) {
    if (!TOKEN) return;
    var allDown = services.every(function(s){ return s.desired === 0 && s.running === 0; });
    document.getElementById('btn-start').disabled = !allDown;
    document.getElementById('btn-stop').disabled  = allDown;
  }
  function disableActions() {
    document.getElementById('btn-start').disabled = true;
    document.getElementById('btn-stop').disabled = true;
  }

  /* ── status fetch ── */
  async function loadStatus() {
    document.getElementById('btn-refresh').disabled = true;
    try {
      var r = await fetch(BASE + '?action=status&token=' + encodeURIComponent(TOKEN));
      if (r.status === 403) { log('Access denied — invalid token.', 'err'); return; }
      var d = await r.json();
      if (d.error)    { log(d.error, 'warn'); renderUnknownCards(); disableActions(); return; }
      if (d.warning)  { log(d.warning, 'warn'); }
      if (d.services) {
        renderCards(d.services);
        if (d.unavailable) {
          disableActions();
        } else {
          updateButtons(d.services);
        }
        document.getElementById('ts').textContent = new Date().toLocaleTimeString();
      }
    } catch(e) { log('Status fetch failed: ' + e.message, 'err'); }
    finally { document.getElementById('btn-refresh').disabled = false; }
  }

  /* ── start / stop ── */
  async function doAction(action) {
    if (busy) return;
    if (action === 'stop' && !confirm('Stop all demo services?')) return;
    busy = true;
    log(action === 'start' ? 'Starting services…' : 'Stopping services…', 'info');
    document.getElementById('btn-start').disabled = true;
    document.getElementById('btn-stop').disabled  = true;
    try {
      var r = await fetch(BASE + '?action=' + action + '&token=' + encodeURIComponent(TOKEN), { method: 'POST' });
      var d = await r.json();
      if (r.ok && d.ok) {
        log(d.message || 'Done.', 'ok');
        /* poll aggressively for 3 min then settle back to 15 s */
        var polls = 0;
        var pollId = setInterval(async function() {
          await loadStatus(); polls++;
          if (polls >= 18) clearInterval(pollId);
        }, 10000);
      } else { log((d.error || d.message || 'Unknown error'), 'err'); }
    } catch(e) { log('Request failed: ' + e.message, 'err'); }
    finally { busy = false; }
  }

  /* expose for onclick */
  window.doAction   = doAction;
  window.loadStatus = loadStatus;

  /* ── init ── */
  loadStatus();
  setInterval(loadStatus, 15000);
})();
</script>
</body>
</html>"""


# ── helpers ───────────────────────────────────────────────────────────────────

def _auth(event: dict) -> bool:
    """Constant-time token comparison. Returns True if auth passes."""
    if not CONTROL_TOKEN:
        return True  # no token configured — open (useful during initial deploy test)
    token = (event.get("queryStringParameters") or {}).get("token", "")
    return hmac.compare_digest(token, CONTROL_TOKEN)


def _placeholder_services() -> list[dict]:
    return [
        {
            "name": service,
            "desired": 0,
            "running": 0,
            "pending": 0,
            "rolloutState": "UNKNOWN",
        }
        for service in SERVICES
    ]


def _friendly_client_error(exc: Exception, action: str) -> str:
    if not isinstance(exc, ClientError):
        if action == "status":
            return "Status is temporarily unavailable. Refresh in a few moments."
        return "The request could not be completed right now. Please try again."

    code = exc.response.get("Error", {}).get("Code", "")
    if code in {"ClusterNotFoundException", "ServiceNotFoundException"}:
        if action == "status":
            return "Status is temporarily unavailable. The control panel cannot read the demo services right now."
        return "The demo services are not reachable from the control plane right now. Please refresh and try again."
    if code in {"AccessDeniedException", "UnauthorizedOperation"}:
        return "The control panel does not currently have permission to manage the demo services."
    return "Status is temporarily unavailable. Refresh in a few moments." if action == "status" else "The request could not be completed right now. Please try again."


def _status() -> dict:
    client = boto3.client("ecs", region_name=ECS_REGION)
    resp = client.describe_services(cluster=CLUSTER, services=SERVICES)
    out = []
    for svc in resp["services"]:
        primary = next(
            (d for d in svc["deployments"] if d["status"] == "PRIMARY"), {}
        )
        out.append(
            {
                "name":         svc["serviceName"],
                "desired":      svc["desiredCount"],
                "running":      svc["runningCount"],
                "pending":      svc["pendingCount"],
                "rolloutState": primary.get("rolloutState", "UNKNOWN"),
            }
        )
    return {"services": out, "cluster": CLUSTER, "region": ECS_REGION}


def _set_count(count: int) -> None:
    client = boto3.client("ecs", region_name=ECS_REGION)
    for svc in SERVICES:
        client.update_service(cluster=CLUSTER, service=svc, desiredCount=count)


def _resp(status: int, body, content_type: str = "application/json") -> dict:
    return {
        "statusCode": status,
        "headers":    {"Content-Type": content_type},
        "body":       json.dumps(body) if content_type == "application/json" else body,
    }


# ── handler ───────────────────────────────────────────────────────────────────

def lambda_handler(event, _context):
    method = (
        event.get("requestContext", {}).get("http", {}).get("method", "GET").upper()
    )
    action = (event.get("queryStringParameters") or {}).get("action", "")

    # Auth check on every request
    if not _auth(event):
        return _resp(403, {"error": "Forbidden"})

    # ── GET / → HTML page ───────────────────────────────────────────────────
    if not action:
        page = HTML_PAGE.replace("DEMO_URL_PLACEHOLDER", DEMO_URL)
        return _resp(200, page, "text/html; charset=utf-8")

    # ── GET ?action=status ──────────────────────────────────────────────────
    if action == "status" and method == "GET":
      try:
        return _resp(200, _status())
      except Exception as exc:
        return _resp(200, {
          "services": _placeholder_services(),
          "cluster": CLUSTER,
          "region": ECS_REGION,
          "unavailable": True,
          "warning": _friendly_client_error(exc, "status"),
        })

    # ── POST ?action=start ──────────────────────────────────────────────────
    if action == "start" and method == "POST":
      try:
        _set_count(1)
        return _resp(200, {"ok": True, "message": "Services starting — check status in ~2 min."})
      except Exception as exc:
        return _resp(500, {"ok": False, "error": _friendly_client_error(exc, "start")})

    # ── POST ?action=stop ───────────────────────────────────────────────────
    if action == "stop" and method == "POST":
      try:
        _set_count(0)
        return _resp(200, {"ok": True, "message": "Services stopping — tasks draining now."})
      except Exception as exc:
        return _resp(500, {"ok": False, "error": _friendly_client_error(exc, "stop")})

    return _resp(400, {"error": f"Unknown action: {action!r}"})
