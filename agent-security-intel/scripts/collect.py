#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI Agent / AgentOS 安全每日情报采集器。

数据源：GitHub（watchlist + 新星/活跃搜索）、arXiv、安全 RSS、会议静态目录。
输出：reports/intel-YYYY-MM-DD.md + data/latest-items.json + data/state.json（去重与趋势）
仅依赖 Python 标准库。可选环境变量 GITHUB_TOKEN 提升 API 配额。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)
from html import unescape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
STATE_PATH = os.path.join(ROOT, "data", "state.json")
REPORT_DIR = os.path.join(ROOT, "reports")
ITEMS_PATH = os.path.join(ROOT, "data", "latest-items.json")
UA = {"User-Agent": "Mozilla/5.0 (agent-security-intel; daily-brief)"}

with open(CONFIG_PATH, encoding="utf-8") as f:
    CFG = json.load(f)


# ---------------------------------------------------------------- utilities
def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"seen": {}, "gh_snapshot": {}, "history": {}}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def score_text(text):
    """按关键词权重打分，返回 (score, 命中关键词列表)。"""
    low = (text or "").lower()
    score, hits = 0, []
    for kw, w in CFG["keywords"].items():
        if kw.lower() in low:
            score += w
            hits.append(kw)
    return score, hits


def tag_text(text):
    low = (text or "").lower()
    tags = []
    for tag, words in CFG["tag_rules"].items():
        if any(w.lower() in low for w in words):
            tags.append(tag)
    return tags or ["综合"]


def source_status(status, name):
    return {"name": name, "status": status}


# ---------------------------------------------------------------- collectors
def collect_github(state, statuses, cutoff_days=14):
    """返回 (新星仓库, 活跃仓库, watchlist 动态) 三类条目。"""
    gh_cfg = CFG["github"]
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "agent-security-intel"}
    if token:
        headers["Authorization"] = "Bearer " + token

    def gh(path, params=None):
        url = "https://api.github.com" + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=headers)
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    return json.load(r), None
            except urllib.error.HTTPError as e:
                if e.code in (403, 429) and attempt == 0:
                    time.sleep(65)  # 匿名搜索配额 10 次/分钟，等窗口重置后重试一次
                    continue
                hint = "（限流，可设置 GITHUB_TOKEN 环境变量）" if e.code in (403, 429) else ""
                return None, "HTTP %s %s%s" % (e.code, e.reason[:40], hint)
            except Exception as e:
                return None, str(e)[:60]

    def gh_throttled(path, params=None):
        time.sleep(7)  # 匿名搜索限速：请求间隔拉开，避免整分钟配额被打爆
        return gh(path, params)

    new_items, active_items, watch_items = [], [], []
    seen_urls = set()

    def add_unique(bucket, item):
        if item.get("url"):
            if item["url"] in seen_urls:
                return
            seen_urls.add(item["url"])
        bucket.append(item)

    def repo_item(meta, kind):
        full = meta["full_name"]
        url = meta["html_url"]
        prev = state.get("gh_snapshot", {}).get(full, {})
        delta = meta["stargazers_count"] - prev.get("stars", meta["stargazers_count"])
        text = full + " " + (meta.get("description") or "")
        score, hits = score_text(text)
        return {
            "kind": kind, "title": full, "url": url,
            "stars": meta["stargazers_count"], "star_delta": delta,
            "pushed_at": meta["pushed_at"][:10],
            "created_at": meta.get("created_at", "")[:10],
            "desc": (meta.get("description") or "")[:220],
            "lang": meta.get("language") or "-",
            "score": score, "hits": hits[:6], "tags": tag_text(text),
            "date": meta["pushed_at"][:10],
        }

    for search in gh_cfg["emerging_searches"] + gh_cfg["active_searches"]:
        q = search["q"].replace("{cutoff}", (utcnow() - timedelta(days=cutoff_days)).strftime("%Y-%m-%d"))
        data, err = gh_throttled("/search/repositories", {"q": q, "sort": "stars", "order": "desc", "per_page": 15})
        if err:
            statuses.append(source_status("FAIL: " + err, "GitHub搜索:" + search["label"]))
            continue
        is_new = search in gh_cfg["emerging_searches"]
        for meta in data.get("items", []):
            add_unique(new_items if is_new else active_items,
                       repo_item(meta, "gh_new" if is_new else "gh_active"))
        statuses.append(source_status("OK (%d条)" % data.get("total_count", 0), "GitHub搜索:" + search["label"]))

    # watchlist 批量获取：一条 repo: 限定搜索替代 N 次 /repos 调用，节省核心 API 配额
    wl = gh_cfg["watchlist"]
    by_name = {}
    for i in range(0, len(wl), 30):
        chunk = wl[i:i + 30]
        q = " ".join("repo:" + r for r in chunk)
        data, err = gh_throttled("/search/repositories", {"q": q, "per_page": 100})
        if err:
            statuses.append(source_status("FAIL: " + err, "GitHub watchlist(批量)"))
            continue
        for meta in data.get("items", []):
            by_name[meta["full_name"].lower()] = meta
    missing = [r for r in wl if r.lower() not in by_name]
    for repo in missing[:10]:  # 兜底：逐个拉取（配额耗尽时自然失败并如实上报）
        data, err = gh("/repos/" + repo)
        if err:
            watch_items.append({"kind": "gh_watch", "title": repo, "url": "https://github.com/" + repo,
                                "error": err, "score": 0, "hits": [], "tags": [], "desc": "", "date": ""})
            continue
        add_unique(watch_items, repo_item(data, "gh_watch"))
    for r in wl:
        meta = by_name.get(r.lower())
        if meta:
            add_unique(watch_items, repo_item(meta, "gh_watch"))
    ok = sum(1 for w in watch_items if "error" not in w)
    statuses.append(source_status("OK %d/%d" % (ok, len(watch_items)), "GitHub watchlist"))

    new_items.sort(key=lambda x: -x["stars"])
    active_items.sort(key=lambda x: (-x["score"], -x["stars"]))
    watch_items.sort(key=lambda x: -x.get("star_delta", 0))
    return new_items, active_items, watch_items


ARXIV_NS = {"a": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom"}
# 四大安全顶会信号：arXiv comment 字段常写 "Accepted at USENIX Security 2027" 等
VENUE_RE = re.compile(
    r"(USENIX\s+Security|IEEE\s+S(&amp;|&)\s*P|S(&amp;|&)\s*P\s*'?2\d|Oakland|ACM\s+CCS|\bCCS\s*'?2\d|\bNDSS\b)",
    re.I)
VENUE_BONUS = 10  # 同行评审接收信号加成


def venue_match(text):
    m = VENUE_RE.search(text or "")
    if not m:
        return ""
    s = m.group(0).replace("&amp;", "&")
    for short, full in [("S&P", "IEEE S&P"), ("Oakland", "IEEE S&P"), ("CCS", "ACM CCS")]:
        if short in s:
            return full
    return s


def collect_arxiv(statuses):
    cfg = CFG["arxiv"]
    end = utcnow()
    start = end - timedelta(days=cfg["days"])
    terms = " OR ".join('(all:"%s")' % t for t in cfg["terms"])
    cats = " OR ".join("cat:%s" % c for c in cfg["categories"])
    query = "(%s) AND (%s) AND submittedDate:[%s TO %s]" % (
        terms, cats, start.strftime("%Y%m%d0000"), end.strftime("%Y%m%d2359"))
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode({
        "search_query": query, "sortBy": "submittedDate", "sortOrder": "descending",
        "max_results": cfg["max_results"]})
    items = []
    root = None
    for attempt in range(3):
        try:
            root = ET.fromstring(http_get(url))
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(20 * (attempt + 1))  # arXiv 礼貌性重试：退避后再试
                continue
            break
        except Exception:
            break
    try:
        if root is not None:
            n_venue = 0
            for e in root.findall("a:entry", ARXIV_NS):
                title = re.sub(r"\s+", " ", e.findtext("a:title", "", ARXIV_NS)).strip()
                summary = re.sub(r"\s+", " ", e.findtext("a:summary", "", ARXIV_NS)).strip()
                comment = re.sub(r"\s+", " ", e.findtext("arxiv:comment", "", ARXIV_NS) or "").strip()
                pub = e.findtext("a:published", "", ARXIV_NS)[:10]
                link = e.findtext("a:id", "", ARXIV_NS)
                cats = [c.attrib.get("term", "") for c in e.findall("a:category", ARXIV_NS)]
                text = title + " " + summary
                score, hits = score_text(text)
                tags = tag_text(text)
                venue = venue_match(comment + " " + title)
                if venue:
                    score += VENUE_BONUS
                    n_venue += 1
                    if "顶会" not in tags:
                        tags.append("顶会")
                items.append({"kind": "paper", "title": title, "url": link, "date": pub,
                              "cats": ",".join(cats[:3]),
                              "desc": (("🏆 %s｜" % venue) if venue else "") + summary[:260],
                              "score": score, "hits": hits[:6], "tags": tags,
                              "venue": venue})
            statuses.append(source_status(
                "OK (%d条，四大顶会标记%d条)" % (len(items), n_venue)
                if n_venue else "OK (%d条)" % len(items), "arXiv"))
        else:
            statuses.append(source_status("FAIL: 多次重试后仍失败（arXiv 限流）", "arXiv"))
    except Exception as e:
        statuses.append(source_status("FAIL: " + str(e)[:60], "arXiv"))
    items.sort(key=lambda x: (-x["score"], x["date"]))
    return items


RSS_ITEM_DAYS = None


def collect_rss(statuses):
    statuses_list = []
    items = []
    days = CFG["rss_days"]
    cutoff = utcnow() - timedelta(days=days)
    for feed in CFG["rss"]:
        count = 0
        try:
            root = ET.fromstring(http_get(feed["url"], timeout=20))
            entries = list(root.iter("item")) + list(root.iter("entry"))
            for it in entries:
                title = strip_html(it.findtext("title", ""))
                link = (it.findtext("link") or "").strip()
                if not link:
                    g = it.find("{http://www.w3.org/2005/Atom}link")
                    link = g.attrib.get("href", "") if g is not None else ""
                link = re.sub(r"\?oc=5$", "", link)
                pub = it.findtext("pubDate") or it.findtext("{http://www.w3.org/2005/Atom}published") or ""
                try:
                    # 剥离 RFC 822 时区后缀（GMT/UTC/+0000 等），仅保留本地解析可行的部分
                    pub_local = re.sub(r"\s*(GMT|UTC|Z|[+-]\d{2}:?\d{2}|[+-]\d{4})\s*$", "", pub.strip())
                    dt = datetime.strptime(pub_local, "%a, %d %b %Y %H:%M:%S")
                except Exception:
                    try:
                        dt = datetime.fromisoformat(pub.replace("Z", "").strip()[:19])
                    except Exception:
                        dt = utcnow()
                if dt < cutoff:
                    continue
                desc = strip_html(it.findtext("description", "") or
                                  it.findtext("{http://www.w3.org/2005/Atom}summary", ""))
                text = title + " " + desc[:400]
                score, hits = score_text(text)
                items.append({"kind": "news", "title": title, "url": link,
                              "date": dt.strftime("%Y-%m-%d"), "feed": feed["name"],
                              "desc": desc[:220], "score": score, "hits": hits[:6],
                              "tags": tag_text(text)})
                count += 1
            statuses_list.append(source_status("OK (%d条)" % count, feed["name"]))
        except Exception as e:
            statuses_list.append(source_status("FAIL: " + str(e)[:50], feed["name"]))
    statuses.extend(statuses_list)
    items.sort(key=lambda x: -x["score"])
    return items


# ---------------------------------------------------------------- venues (Big 4)
def collect_venues(state, statuses, today):
    """四大安全顶会（IEEE S&P / ACM CCS / USENIX Security / NDSS）接收列表监控。
    拉取官网 accepted-papers 页面抽取论文标题，state 去重只报新增（首跑建基准）。
    CCS/USENIX 的接收信号由 arXiv comment 通道覆盖（collect_arxiv 的 VENUE_RE）。"""
    v_cfg = CFG.get("venues") or {}
    pages = [p for p in v_cfg.get("pages", []) if p.get("enabled", True)]
    if not pages:
        return []
    base = state.setdefault("venues", {})
    seen = base.setdefault("seen", {})
    min_score = v_cfg.get("min_score", 6)
    items = []

    def parse_titles(html, parser):
        titles = []
        if parser == "single_paper":  # NDSS：single-paper 容器，标题与作者以 3+ 空格分隔
            for block in re.split(r'class="[^"]*single-paper[^"]*"', html)[1:]:
                chunk = block.split("<p class=")[0]
                text = re.sub(r"\s{3,}", " ║ ", strip_html(chunk)).strip(" ║")
                first = text.split("║")[0].strip().lstrip(">").strip()
                if 15 <= len(first) <= 200:
                    titles.append(first)
        elif parser == "list_group":  # IEEE S&P：list-group-item 条目
            for m in re.finditer(r'class="list-group-item[^"]*"[^>]*>(.{15,400}?)</(?:li|div|a)>', html, re.S):
                text = strip_html(m.group(1)).strip()
                if 15 <= len(text) <= 200:
                    titles.append(text)
        return titles

    for page in pages:
        try:
            html = http_get(page["url"], timeout=25).decode("utf-8", "replace")
        except Exception as e:
            statuses.append(source_status("FAIL: %s" % str(e)[:50], "顶会雷达:" + page["name"]))
            continue
        titles = parse_titles(html, page["parser"])
        if not titles:
            statuses.append(source_status("OK (0条·解析为空或列表未公布)", "顶会雷达:" + page["name"]))
            continue
        first_run = not seen.get(page["name"] + "|init")
        fresh = []
        for t in titles:
            key = page["name"] + "|" + t[:120]
            if key in seen:
                continue
            seen[key] = today
            fresh.append(t)
        seen[page["name"] + "|init"] = True
        if first_run:
            statuses.append(source_status(
                "OK (基线建立：%d篇，此后只报新增)" % len(titles), "顶会雷达:" + page["name"]))
            continue
        n_new = n_kept = 0
        for t in fresh:
            score, hits = score_text(t)
            tags = tag_text(t)
            if "顶会" not in tags:
                tags.append("顶会")
            if score >= min_score:
                items.append({"kind": "venue", "title": t,
                              "url": page["url"], "date": today,
                              "desc": "新进入 %s 接收列表（同行评审信号）" % page["name"],
                              "score": score + VENUE_BONUS, "hits": hits[:6], "tags": tags,
                              "venue": page["name"]})
                n_kept += 1
            n_new += 1
        statuses.append(source_status(
            "OK (新增%d篇，%d篇过相关度线)" % (n_new, n_kept), "顶会雷达:" + page["name"]))
    # seen 容量控制
    if len(seen) > 3000:
        for k in sorted(seen, key=seen.get)[:len(seen) - 2000]:
            seen.pop(k, None)
    items.sort(key=lambda x: -x["score"])
    return items


# ---------------------------------------------------------------- deep read
DEEP_COMMIT_WORDS = re.compile(
    r"\b(secur\w*|secure|boot\w*|attest\w*|fault\w*|vulnerab\w*|cve-\d+|exploit\w*|"
    r"trustzone|optee|\bkey\b|keygen|crypto\w*|signing|signed|signature|"
    r"isolat\w*|sandbox\w*|fuzz\w*|harden\w*|flash\w*|\brom\b)", re.I)
DEEP_EVENT_BASE = {"release": 12, "issue": 8, "commit": 6}
DEEP_PRIORITY_BONUS = {"P0": 6, "P1": 3, "P2": 1}


def collect_deep_read(state, statuses, today):
    """经典项目精读：增量驱动，只报新增、无动态静默。
    数据层用 GitHub 公开 Atom feed（releases/commits/issues）而非 REST API：
    无配额限制，彻底绕开匿名 core API 60次/时限制（共享出口 IP 常年打满）。
    第一步仍用 1 次批量 search 拿 pushed_at，无推送的仓库当天零请求。
    首次运行只建立基准不出条目；P2 仅在 config.deep_read.p2_weekday 指定的周几检查。
    返回 (items, stats)。"""
    dr_cfg = CFG.get("deep_read") or {}
    repos = dr_cfg.get("repos", [])
    if not repos:
        return [], None
    p2_weekday = dr_cfg.get("p2_weekday", 0)
    is_p2_day = datetime.strptime(today, "%Y-%m-%d").weekday() == p2_weekday
    todo = [r for r in repos if r["priority"] != "P2" or is_p2_day]
    base = state.setdefault("deep_read", {})
    token = os.environ.get("GITHUB_TOKEN", "")
    gh_headers = {"Accept": "application/vnd.github+json", "User-Agent": "agent-security-intel"}
    if token:
        gh_headers["Authorization"] = "Bearer " + token

    def gh_api(path, params=None):
        url = "https://api.github.com" + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=gh_headers)
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    return json.load(r), None
            except urllib.error.HTTPError as e:
                if e.code in (403, 429) and attempt == 0:
                    time.sleep(65)
                    continue
                return None, "HTTP %s" % e.code
            except Exception as e:
                return None, str(e)[:50]

    def fetch_atom(url):
        """拉取 GitHub 公开 Atom feed，返回 entry 列表（dict: title/link/updated/content）。
        部分端点（如 issues.atom）会校验 Accept/UA，缺失时返回 406。"""
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA["User-Agent"],
                "Accept": "application/atom+xml, application/xml, text/xml, */*"})
            with urllib.request.urlopen(req, timeout=20) as r:
                root = ET.fromstring(r.read())
        except Exception as e:
            return None, str(e)[:50]
        entries = []
        for e in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = strip_html(e.findtext("{http://www.w3.org/2005/Atom}title", ""))
            link_el = e.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.attrib.get("href", "") if link_el is not None else ""
            updated = (e.findtext("{http://www.w3.org/2005/Atom}updated", "") or "")[:19]
            content = strip_html(e.findtext("{http://www.w3.org/2005/Atom}content", ""))
            entries.append({"title": title, "link": link, "updated": updated, "content": content})
        return entries, None

    now_dt = utcnow()
    now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    items, fail_repos = [], []
    checked = quiet = 0

    # 第一步：批量 search 拿 pushed_at / stars（search 配额与 core 独立；30 个仓库一条查询）
    meta_by_repo = {}
    for i in range(0, len(todo), 30):
        chunk = todo[i:i + 30]
        q = " ".join("repo:" + r["repo"] for r in chunk)
        time.sleep(7)  # search 限速 10 次/分钟
        data, err = gh_api("/search/repositories", {"q": q, "per_page": 100})
        if err:
            statuses.append(source_status("FAIL: %s（精读元数据获取失败，本期跳过）" % err, "经典项目精读"))
            return [], None
        for m in data.get("items", []):
            meta_by_repo[m["full_name"].lower()] = m

    def make_item(repo_cfg, event, title, url, date, desc):
        prio = repo_cfg["priority"]
        text = title + " " + desc + " " + repo_cfg.get("why", "")
        score, hits = score_text(text)
        return {"kind": "deep_read", "priority": prio, "why": repo_cfg.get("why", ""),
                "event": event, "title": title, "url": url, "date": date,
                "desc": desc[:260], "score": score + DEEP_EVENT_BASE[event] + DEEP_PRIORITY_BONUS[prio],
                "hits": hits[:6], "tags": tag_text(text)}

    for repo_cfg in todo:
        repo = repo_cfg["repo"]
        prev = base.get(repo, {})
        first_run = not prev
        pushed = (meta_by_repo.get(repo.lower()) or {}).get("pushed_at", "")
        changed = bool(pushed) and pushed[:19] > (prev.get("pushed_at", "0000"))[:19]
        # P0 且 release 基准未建：当天补查一次 releases 建基准
        p0_need_release = repo_cfg["priority"] == "P0" and not prev.get("last_tag")
        new_state = {"checked_at": now_iso, "pushed_at": pushed,
                     "last_tag": prev.get("last_tag")}

        if not first_run and not changed and not p0_need_release:
            checked += 1
            quiet += 1
            base[repo] = new_state
            continue

        repo_failed = False

        # 1) releases feed：新于基准 tag 的正式发布（无基准时只记最新 tag 不报增量）
        if changed or first_run or p0_need_release:
            entries, err = fetch_atom("https://github.com/%s/releases.atom" % repo)
            if err:
                fail_repos.append("%s(releases %s)" % (repo, err))
                repo_failed = True
            elif entries:
                last_tag = prev.get("last_tag")
                for en in entries:
                    tag = en["link"].split("/tag/")[-1] if "/tag/" in en["link"] else ""
                    if tag and last_tag and tag != last_tag:
                        items.append(make_item(repo_cfg, "release",
                            "%s 发布 %s" % (repo, tag), en["link"],
                            en["updated"][:10], en["content"] or en["title"]))
                    if tag:
                        new_state["last_tag"] = tag
                        break

        # 2) commits feed：仅当有推送且非首跑（issues.atom 已于 2026-09-10 被 GitHub
        #    拒绝匿名访问（406），issues 通道下线；releases/commits feed 仍正常）
        if changed and not first_run and not repo_failed:
            entries, err = fetch_atom("https://github.com/%s/commits.atom" % repo)
            if err:
                fail_repos.append("%s(commits %s)" % (repo, err))
            else:
                since = prev.get("checked_at", "")[:19]
                commit_lines = [en["title"] for en in entries
                                if en["updated"] > since and DEEP_COMMIT_WORDS.search(en["title"])][:5]
                if commit_lines:
                    items.append(make_item(repo_cfg, "commit",
                        "%s 近期安全相关提交" % repo, "https://github.com/%s/commits" % repo,
                        today, "；".join(commit_lines)))
            time.sleep(1)  # atom feed 礼貌间隔

        if not repo_failed:
            base[repo] = new_state
            checked += 1
        else:
            checked += 1  # 失败也计为已检查（基准未更新，下次补查增量）

    n_inc = len(items)
    p0 = sum(1 for i in items if i["priority"] == "P0")
    stats = {"checked": checked, "quiet": quiet, "planned": len(todo),
             "p2_day": is_p2_day, "increments": n_inc, "p0_inc": p0}
    if fail_repos:
        statuses.append(source_status(
            "WARN: %d仓增量/%d仓检查；失败: %s" % (n_inc, checked, "; ".join(fail_repos[:4])),
            "经典项目精读"))
    else:
        statuses.append(source_status("OK (%d仓增量/%d仓检查)" % (n_inc, checked), "经典项目精读"))
    items.sort(key=lambda x: (-(x["priority"] == "P0"), -x["score"]))
    return items, stats


# ---------------------------------------------------------------- top1
def rank_candidates(items_by_key):
    """全部条目按 相关度+跨层加成+新信号优先 排序；watchlist 日常动态不参选。"""
    cands = []
    for key, group in items_by_key.items():
        for it in group:
            if "error" in it or not it.get("url"):
                continue
            if it.get("kind") == "gh_watch":
                continue
            cross = len([t for t in it.get("tags", []) if t != "综合"])
            prio = (it.get("score", 0) + 4 * max(0, cross - 1)
                    + (3 if it.get("kind") == "paper" else 0)
                    + (3 if it.get("kind") == "venue" else 0)  # 顶会接收=同行评审信号
                    + (2 if it.get("kind") == "gh_new" else 0))
            cands.append((prio, it))
    cands.sort(key=lambda x: -x[0])
    return [it for _, it in cands]


def pick_top1(items_by_key):
    """评选当日 Top1。"""
    ranked = rank_candidates(items_by_key)
    return ranked[0] if ranked else None


def fetch_detail(item):
    """预取 Top1 原文材料：论文取完整摘要+作者，仓库取 README，新闻取正文文本。失败容忍。"""
    detail = {"fetched": "", "source_type": item.get("kind", "")}
    try:
        if item.get("kind") == "paper":
            m = re.search(r"abs/([0-9.]+)", item["url"])
            if m:
                api = ("http://export.arxiv.org/api/query?id_list=" + m.group(1))
                root = ET.fromstring(http_get(api, timeout=20))
                e = root.find("a:entry", ARXIV_NS)
                if e is not None:
                    authors = ", ".join(a.findtext("a:name", "", ARXIV_NS)
                                       for a in e.findall("a:author", ARXIV_NS)[:8])
                    summary = re.sub(r"\s+", " ", e.findtext("a:summary", "", ARXIV_NS)).strip()
                    detail["fetched"] = "作者: %s\n\n完整摘要: %s" % (authors, summary)
        elif str(item.get("kind", "")).startswith("gh"):
            for fn in ("README.md", "readme.md", "README_zh.md", "README"):
                try:
                    raw = http_get("https://raw.githubusercontent.com/%s/HEAD/%s"
                                   % (item["title"], fn), timeout=20).decode("utf-8", "replace")
                    if raw.strip() and not raw.startswith("404"):
                        detail["fetched"] = raw[:6000]
                        break
                except Exception:
                    continue
        elif item.get("kind") == "news":
            html = http_get(item["url"], timeout=20).decode("utf-8", "replace")
            text = strip_html(re.sub(r"(?is)<(script|style).*?</\1>", " ", html))
            detail["fetched"] = text[:4000]
    except Exception as e:
        detail["fetched"] = "（预取失败：%s，请直接打开链接分析）" % str(e)[:80]
    return detail


# ---------------------------------------------------------------- report
def fmt_item(it, mark_new, idx):
    icon = {"paper": "📄", "gh_new": "🌱", "gh_active": "🔥", "gh_watch": "⭐",
            "news": "🛰️", "deep_read": "📖", "venue": "🏆"}.get(it.get("kind"), "•")
    tags = "/".join(it.get("tags", [])[:2])
    head = "%d. %s %s[%s] %s" % (idx, icon, "🆕 " if mark_new else "", tags, it["title"])
    meta = []
    if it.get("kind", "").startswith("gh"):
        meta.append("⭐%s" % format(it.get("stars", 0), ","))
        if it.get("star_delta"):
            meta.append("七日+{:,}".format(it["star_delta"]))
        if it.get("lang", "-") != "-":
            meta.append(it["lang"])
        if it.get("pushed_at"):
            meta.append("更新 " + it["pushed_at"])
    else:
        if it.get("date"):
            meta.append(it["date"])
        if it.get("feed"):
            meta.append(it["feed"])
        if it.get("cats"):
            meta.append(it["cats"])
        if it.get("score"):
            meta.append("相关度%d" % it["score"])
    line = "%s  —  %s" % (head, " · ".join(meta))
    body = ""
    if it.get("kind") == "deep_read":
        event_cn = {"release": "🔖 版本发布", "commit": "🔧 安全相关提交", "issue": "⚠️ 安全议题"}[it.get("event", "commit")]
        body = "\n   %s · %s | 定位: %s" % (event_cn, it.get("priority", ""), it.get("why", ""))
    if it.get("desc"):
        body += "\n   > %s" % it["desc"].replace("\n", " ")
    if it.get("error"):
        body += "\n   ⚠️ 获取失败: %s" % it["error"]
    return line + "\n   <%s>%s" % (it.get("url", ""), body)


def build_report(items_by_key, statuses, state, today, top1=None, ranked=None, deep_stats=None):
    R = CFG["report"]
    papers, gh_new, gh_active, gh_watch, news, deep, venues = (items_by_key[k] for k in
        ["paper", "gh_new", "gh_active", "gh_watch", "news", "deep_read", "venue"])
    seen = state.setdefault("seen", {})
    def is_new(it):
        return it.get("url") and it["url"] not in seen

    # 安全相关度过滤：低分仓库退居次位，仅在数量不足时补充展示
    def pick_gh(bucket, n):
        hot = [g for g in bucket if g.get("score", 0) >= R["gh_min_score"]]
        rest = [g for g in bucket if g.get("score", 0) < R["gh_min_score"]]
        out = hot + rest
        if len(hot) < 5:
            out = hot + rest[:5 - len(hot)]
        return out[:n]

    gh_new_show = pick_gh(gh_new, R["top_gh_new"])
    gh_active_show = pick_gh(gh_active, R["top_gh_new"])
    news_show = [n for n in news if n["score"] >= R["news_min_score"]][:R["top_news"]]
    gh_watch_ok = [w for w in gh_watch if "error" not in w]

    L = []
    L.append("# AI Agent / AgentOS 安全 · 每日情报 №%s" % today)
    L.append("")
    L.append("> 采集时间：%s（本地）｜数据源 %d 个（健康度见附录）" % (
        datetime.now().strftime("%Y-%m-%d %H:%M"), len(statuses)))
    L.append("")

    # 今日要点：全部条目统一排序的 Top N 榜单（世界要抓关键信息）
    board = (ranked or [])[:R.get("top_n", 10)]
    if board:
        L.append("## 🎯 今日要点（Top %d · 综合关键度排序）" % len(board))
        L.append("")
        L.append("> 排序 = 相关度（关键词加权）+ 跨层加成 + 顶会接收 🏆 加成 + 新信号优先；watchlist 日常星增动态不参选。第 1 名附深度分析。")
        L.append("")
        for i, it in enumerate(board, 1):
            L.append(fmt_item(it, is_new(it), i))
            L.append("")
            if i == 1 and it is top1:
                cross = "、".join(t for t in it.get("tags", []) if t != "综合") or "单层"
                L.append("**入选理由**：相关度 %d ｜ 层级定位：%s" % (it.get("score", 0), cross))
                L.append("")
                L.append("<!-- top1-analysis: 分析师在此插入深度分析（是什么/技术机制/证据强度/四层定位/影响与对策） -->")
                L.append("")
        if len(board) > 1:
            L.append("<!-- top-briefs: 对第 2-%d 名逐条插入一句话简评（为什么值得关注/与哪条同线），格式为 markdown 列表 -->" % len(board))
            L.append("")

    # 其余雷达：数字摘要（榜单之外的完整数据在 data/latest-items.json）
    L.append("## 📊 其余雷达（数字摘要）")
    L.append("")
    ok_cnt = sum(1 for s in statuses if s["status"].startswith("OK"))
    venue_show = venues[:CFG.get("venues", {}).get("top_show", 10)]
    deep_show = deep[:R.get("top_deep", 12)]
    deep_note = "P0/P1 每日，P2 每周一"
    if deep_stats:
        deep_note += "｜检查 %d/%d 仓，%d 仓增量" % (
            deep_stats.get("checked", 0), deep_stats.get("planned", 0),
            deep_stats.get("increments", 0))
    L.append("| 维度 | 今日条目 | 说明 |")
    L.append("|---|---|---|")
    L.append("| 📄 论文雷达 | %d | arXiv 近 %d 天（comment 含顶会接收标记 🏆） |" % (len(papers), CFG["arxiv"]["days"]))
    L.append("| 🏆 顶会雷达 | %d/%d | Big 4 接收列表增量（同行评审信号） |" % (len(venue_show), len(venues)))
    L.append("| 🌱 GitHub 新星 | %d/%d | 近 14 天新建（安全相关优先） |" % (len(gh_new_show), len(gh_new)))
    L.append("| 🔥 GitHub 活跃 | %d/%d | 近 7 天活跃 |" % (len(gh_active_show), len(gh_active)))
    L.append("| ⭐ Watchlist | %d/%d | 成熟项目星标/更新动态 |" % (len(gh_watch_ok), len(CFG["github"]["watchlist"])))
    L.append("| 📖 经典精读 | %d/%d | %s |" % (len(deep_show), len(deep), deep_note))
    L.append("| 🛰️ 安全资讯 | %d/%d | RSS 相关度≥%d 条目 |" % (len(news_show), len(news), R["news_min_score"]))
    L.append("| ✅ 源健康度 | %d/%d | 正常采集的源数量 |" % (ok_cnt, len(statuses)))
    L.append("")
    L.append("- 完整结构化数据见 `data/latest-items.json`（全部条目含 score/hits/tags 字段，可二次加工检索）。")
    L.append("")

    # trends
    L.append("## 📈 趋势信号（自动统计）")
    L.append("")
    kw_count = {}
    for group in items_by_key.values():
        for it in group:
            for kw in it.get("hits", []):
                kw_count[kw] = kw_count.get(kw, 0) + 1
    top_kw = sorted(kw_count.items(), key=lambda kv: -kv[1])[:12]
    hist = state.get("history", {})
    prev_dates = sorted([d for d in hist if d < today])
    prev = hist.get(prev_dates[-1], {}) if prev_dates else {}
    rising = [(k, c, prev.get(k, 0)) for k, c in top_kw if c > prev.get(k, 0)]
    if top_kw:
        L.append("热词频次：" + "、".join("`%s`×%d" % (k, c) for k, c in top_kw))
    if prev:
        L.append("")
        L.append("较上期（%s）上升：%s" % (prev_dates[-1],
            "、".join("`%s` %d→%d" % (k, p, c) for k, c, p in rising[:6]) or "无明显上升热词"))
    else:
        L.append("")
        L.append("首期运行，暂无历史对比；此后每期将自动对比热词升降。")
    if gh_new:
        fastest = next((g for g in gh_new if g.get("score", 0) >= R["gh_min_score"]), gh_new[0])
        L.append("")
        L.append("增速最快新仓库：[%s](%s)（⭐%s，%s）" % (fastest["title"], fastest["url"],
            format(fastest["stars"], ","), fastest["desc"][:80]))
    L.append("")

    # analyst notes
    notes_path = os.path.join(ROOT, "data", "editor-notes.md")
    if os.path.exists(notes_path):
        with open(notes_path, encoding="utf-8") as f:
            notes = f.read().strip()
        if notes:
            L.append("## 🧠 分析师点评")
            L.append("")
            L.append(notes)
            L.append("")

    # appendix
    L.append("## 附录 · 数据源状态")
    L.append("")
    L.append("| 数据源 | 状态 |")
    L.append("|---|---|")
    for s in statuses:
        L.append("| %s | %s |" % (s["name"], s["status"]))
    L.append("")
    L.append("---")
    L.append("*本报告由 agent-security-intel 自动采集生成；条目均为外部链接，仅供安全研究与学习参考。*")
    return "\n".join(L)


# ---------------------------------------------------------------- apply analysis
def apply_analysis(analysis_path, today):
    """把 LLM 分析 JSON（top1_analysis/top3_briefs/editor_notes）填入今日报告。
    幂等：占位注释已被替换的段落直接跳过，不会重复插入。"""
    with open(analysis_path, encoding="utf-8") as f:
        a = json.load(f)
    report_path = os.path.join(REPORT_DIR, "intel-%s.md" % today)
    if not os.path.exists(report_path):
        sys.exit("报告不存在，请先运行采集：%s" % report_path)
    with open(report_path, encoding="utf-8") as f:
        text = f.read()

    def replace_placeholder(text, marker, content):
        if marker not in text:
            print("(skip: %s 已填充或不存在)" % marker)
            return text
        out, replaced = [], False
        for line in text.split("\n"):
            if not replaced and line.strip().startswith(marker):
                out.append(content)
                replaced = True
            else:
                out.append(line)
        return "\n".join(out)

    if a.get("top1_analysis"):
        text = replace_placeholder(
            text, "<!-- top1-analysis:",
            "### 🔍 深度分析\n\n" + a["top1_analysis"].strip())
    top_briefs = a.get("top_briefs") or a.get("top3_briefs")
    if top_briefs:
        text = replace_placeholder(text, "<!-- top-briefs:", top_briefs.strip())
        text = replace_placeholder(text, "<!-- top3-briefs:", top_briefs.strip())
    if a.get("editor_notes"):
        if ("**%s 点评：**" % today) in text:
            print("(skip: editor_notes 今日已填充)")
        else:
            note = a["editor_notes"].strip()
            block = "**%s 点评：**\n\n%s\n\n---" % (today, note)
            if "## 🧠 分析师点评" in text:
                text = text.replace("## 🧠 分析师点评\n",
                                    "## 🧠 分析师点评\n\n%s\n\n" % block, 1)
            else:
                text += "\n## 🧠 分析师点评\n\n%s\n" % block
            notes_path = os.path.join(ROOT, "data", "editor-notes.md")
            old = ""
            if os.path.exists(notes_path):
                with open(notes_path, encoding="utf-8") as f:
                    old = f.read()
            with open(notes_path, "w", encoding="utf-8") as f:
                f.write("**%s 点评：**\n\n%s\n\n%s" % (today, note, old))

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(text)
    print("analysis applied -> %s" % report_path)


# ---------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser(description="AI Agent 安全每日情报采集器")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--skip-gh", action="store_true", help="跳过 GitHub 采集")
    parser.add_argument("--skip-arxiv", action="store_true")
    parser.add_argument("--skip-rss", action="store_true")
    parser.add_argument("--skip-deep", action="store_true", help="跳过经典项目精读")
    parser.add_argument("--skip-venues", action="store_true", help="跳过四大顶会雷达")
    parser.add_argument("--json-only", action="store_true", help="只导出 JSON，不写报告")
    parser.add_argument("--apply-analysis", metavar="FILE",
                        help="把 LLM 分析 JSON（top1_analysis/top3_briefs/editor_notes）填入今日报告后退出")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if args.apply_analysis:
        apply_analysis(args.apply_analysis, args.date)
        return

    state = load_state()
    statuses = []
    papers, gh_new, gh_active, gh_watch, news, deep_items, venue_items = [], [], [], [], [], [], []
    deep_stats = None

    if not args.skip_gh:
        gh_new, gh_active, gh_watch = collect_github(state, statuses)
    else:
        statuses.append(source_status("SKIP", "GitHub 全部"))
    if not args.skip_arxiv:
        papers = collect_arxiv(statuses)
    else:
        statuses.append(source_status("SKIP", "arXiv"))
    if not args.skip_rss:
        news = collect_rss(statuses)
        # 不同源转载同一事件：按标题去重，保留相关度最高的一条
        uniq = {}
        for it in news:
            key = re.sub(r"\s+", " ", it["title"].lower()).strip()
            if key not in uniq or it["score"] > uniq[key]["score"]:
                uniq[key] = it
        news = sorted(uniq.values(), key=lambda x: -x["score"])
    else:
        statuses.append(source_status("SKIP", "RSS 全部"))
    if not args.skip_deep:
        deep_items, deep_stats = collect_deep_read(state, statuses, args.date)
    else:
        statuses.append(source_status("SKIP", "经典项目精读"))
    if not args.skip_venues:
        venue_items = collect_venues(state, statuses, args.date)
    else:
        statuses.append(source_status("SKIP", "四大顶会雷达"))

    items_by_key = {"paper": papers, "gh_new": gh_new, "gh_active": gh_active,
                    "gh_watch": gh_watch, "news": news, "deep_read": deep_items,
                    "venue": venue_items}
    all_items = [it for g in items_by_key.values() for it in g]

    # Top1 评选与原文预取（预取材料存 data/top1.json，供分析师/LLM 深度分析）
    ranked = rank_candidates(items_by_key)
    top1 = ranked[0] if ranked else None
    top1_payload = None
    if top1:
        top1_payload = dict(top1)
        top1_payload["detail"] = fetch_detail(top1)
    if ranked[1:]:
        top1_payload = top1_payload or {}
        top1_payload["runner_ups"] = [
            {k: it.get(k) for k in ("kind", "title", "url", "date", "score", "tags", "desc")}
            for it in ranked[1:CFG["report"].get("top_n", 10)]]

    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    with open(ITEMS_PATH, "w", encoding="utf-8") as f:
        json.dump({"date": args.date, "statuses": statuses, "items": all_items},
                  f, ensure_ascii=False, indent=1)
    if top1_payload:
        with open(os.path.join(ROOT, "data", "top1.json"), "w", encoding="utf-8") as f:
            json.dump(top1_payload, f, ensure_ascii=False, indent=1)

    if args.json_only:
        print("items=%d -> %s" % (len(all_items), ITEMS_PATH))
        return

    report = build_report(items_by_key, statuses, state, args.date,
                          top1=top1, ranked=ranked, deep_stats=deep_stats)
    os.makedirs(REPORT_DIR, exist_ok=True)
    report_path = os.path.join(REPORT_DIR, "intel-%s.md" % args.date)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    # 更新状态：去重指纹、GitHub 星标快照、热词历史
    seen = state.setdefault("seen", {})
    for it in all_items:
        if it.get("url"):
            seen.setdefault(it["url"], args.date)
    if len(seen) > 8000:
        for k in sorted(seen, key=seen.get)[:len(seen) - 6000]:
            seen.pop(k, None)
    snap = state.setdefault("gh_snapshot", {})
    for it in gh_watch:
        if "error" not in it:
            snap[it["title"]] = {"stars": it.get("stars", 0), "pushed_at": it.get("pushed_at", "")}
    kw_count = {}
    for it in all_items:
        for kw in it.get("hits", []):
            kw_count[kw] = kw_count.get(kw, 0) + 1
    state.setdefault("history", {})[args.date] = kw_count
    save_state(state)

    print("report -> %s" % report_path)
    print("items: papers=%d gh_new=%d gh_active=%d watch=%d news=%d deep_read=%d venues=%d"
          % (len(papers), len(gh_new), len(gh_active), len(gh_watch), len(news), len(deep_items), len(venue_items)))
    for s in statuses:
        print("  [%s] %s" % (s["status"], s["name"]))


if __name__ == "__main__":
    main()
