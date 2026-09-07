# -*- coding: utf-8 -*-
"""Probe GitHub API for agent-security landscape (one-off research probe)."""
import json
import sys
import urllib.parse
import urllib.request

def gh(path, params=None):
    url = "https://api.github.com" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": "intel-bot"}
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)
    except Exception as e:
        return {"error": str(e)}

def show(tag, data, limit=10):
    print("\n=== %s ===" % tag)
    if "error" in data:
        print("ERROR:", data["error"])
        return
    for it in data.get("items", [])[:limit]:
        desc = (it.get("description") or "")[:110].replace("\n", " ")
        print("%s | stars=%s | push=%s | %s" % (it["full_name"], it["stargazers_count"], it["pushed_at"][:10], desc))

if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "AI agent security"
    data = gh("/search/repositories", {"q": q, "sort": "stars", "order": "desc", "per_page": 10})
    show(q, data)
