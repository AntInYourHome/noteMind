# -*- coding: utf-8 -*-
"""Probe watchlist repos + emerging repos + arXiv/RSS reachability."""
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

WATCHLIST = [
    "NVIDIA/garak", "microsoft/PyRIT", "promptfoo/promptfoo", "protectai/llm-guard",
    "NVIDIA/NeMo-Guardrails", "guardrails-ai/guardrails", "EPFL-INFO/agentic-security",
    "invariantlabs-ai/mcp-scan", "ethz-spylab/agentdojo", "msoedov/agentic_security",
    "llmware-ai/llmware", "langfuse/langfuse", "helicone/helicone", "lauriewired/whispers",
    "0xPlaygrounds/rig", "modelcontextprotocol/servers", "OWASP/www-project-top-10-for-large-language-model-applications",
    "tldrsec/tldr-sec", "AgentOps-AI/agentops", "Aliasrobotics/LLM-xss",
    "cofounder-ai/cofounder", "leondz/garak", "meta-llama/PurpleLlama",
]

def main():
    print("== WATCHLIST ==")
    for repo in WATCHLIST:
        d = gh("/repos/" + repo)
        if "error" in d:
            print("%-70s MISSING (%s)" % (repo, d["error"][:40]))
            continue
        desc = (d.get("description") or "")[:90].replace("\n", " ")
        print("%-70s stars=%-7s push=%s | %s" % (repo, d["stargazers_count"], d["pushed_at"][:10], desc))

    print("\n== EMERGING (created>2026-08-24, agent security, sort=stars) ==")
    d = gh("/search/repositories", {"q": "agent security created:>2026-08-24", "sort": "stars", "order": "desc", "per_page": 10})
    if "error" not in d:
        for it in d.get("items", []):
            desc = (it.get("description") or "")[:100].replace("\n", " ")
            print("%s | stars=%s | %s" % (it["full_name"], it["stargazers_count"], desc))

    print("\n== EMERGING (created>2026-08-24, MCP/prompt, sort=stars) ==")
    d = gh("/search/repositories", {"q": "MCP OR prompt-injection created:>2026-08-24", "sort": "stars", "order": "desc", "per_page": 10})
    if "error" not in d:
        for it in d.get("items", []):
            desc = (it.get("description") or "")[:100].replace("\n", " ")
            print("%s | stars=%s | %s" % (it["full_name"], it["stargazers_count"], desc))

if __name__ == "__main__":
    main()
