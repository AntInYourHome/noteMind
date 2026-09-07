# -*- coding: utf-8 -*-
"""Probe arXiv API and security RSS feeds reachability."""
import re
import urllib.request
import xml.etree.ElementTree as ET

UA = {"User-Agent": "Mozilla/5.0 (intel-bot)"}

ARXIV_Q = '(all:"prompt injection" OR all:"agent security" OR all:"LLM agent" OR all:"agentic AI" OR all:"MCP" OR all:"jailbreak") AND (cat:cs.CR OR cat:cs.AI OR cat:cs.CL)'

def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def probe_arxiv():
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode({
        "search_query": ARXIV_Q, "sortBy": "submittedDate", "sortOrder": "descending", "max_results": 8,
    })
    try:
        data = fetch(url)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(data)
        print("== ARXIV (latest 8) ==")
        for e in root.findall("a:entry", ns):
            title = re.sub(r"\s+", " ", e.findtext("a:title", "", ns)).strip()
            pub = e.findtext("a:published", "", ns)[:10]
            link = e.findtext("a:id", "", ns)
            print("%s | %s | %s" % (pub, title[:95], link))
    except Exception as ex:
        print("ARXIV ERROR:", ex)

FEEDS = [
    ("TheHackerNews", "https://feeds.feedburner.com/TheHackersNews"),
    ("BleepingComputer", "https://www.bleepingcomputer.com/feed/"),
    ("DarkReading", "https://www.darkreading.com/rss.xml"),
    ("SecurityWeek", "https://feeds.feedburner.com/securityweek"),
    ("Schneier", "https://www.schneier.com/feed/"),
    ("GoogleNews-AI-security", "https://news.google.com/rss/search?q=AI+agent+security&hl=en-US&gl=US&ceid=US:en"),
]

def probe_feeds():
    print("\n== RSS FEEDS ==")
    for name, url in FEEDS:
        try:
            data = fetch(url, timeout=15)
            root = ET.fromstring(data)
            items = root.iter("item")
            first = next(items, None)
            title = first.findtext("title", "").strip() if first is not None else "-"
            print("%-24s OK  items-sample: %s" % (name, title[:80]))
        except Exception as ex:
            print("%-24s FAIL %s" % (name, str(ex)[:70]))

import urllib.parse
if __name__ == "__main__":
    probe_arxiv()
    probe_feeds()
