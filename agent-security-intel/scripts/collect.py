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


ARXIV_NS = {"a": "http://www.w3.org/2005/Atom"}


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
            for e in root.findall("a:entry", ARXIV_NS):
                title = re.sub(r"\s+", " ", e.findtext("a:title", "", ARXIV_NS)).strip()
                summary = re.sub(r"\s+", " ", e.findtext("a:summary", "", ARXIV_NS)).strip()
                pub = e.findtext("a:published", "", ARXIV_NS)[:10]
                link = e.findtext("a:id", "", ARXIV_NS)
                cats = [c.attrib.get("term", "") for c in e.findall("a:category", ARXIV_NS)]
                text = title + " " + summary
                score, hits = score_text(text)
                items.append({"kind": "paper", "title": title, "url": link, "date": pub,
                              "cats": ",".join(cats[:3]), "desc": summary[:260],
                              "score": score, "hits": hits[:6], "tags": tag_text(text)})
            statuses.append(source_status("OK (%d条)" % len(items), "arXiv"))
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
                    dt = datetime.strptime(pub.replace("+0000", "").strip(), "%a, %d %b %Y %H:%M:%S")
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


# ---------------------------------------------------------------- top1
def pick_top1(items_by_key):
    """评选当日 Top1：相关度 + 跨层加成 + 新信号优先；watchlist 日常动态不参选。"""
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
                    + (2 if it.get("kind") == "gh_new" else 0))
            cands.append((prio, it))
    if not cands:
        return None
    cands.sort(key=lambda x: -x[0])
    return cands[0][1]


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
    icon = {"paper": "📄", "gh_new": "🌱", "gh_active": "🔥", "gh_watch": "⭐", "news": "🛰️"}.get(it.get("kind"), "•")
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
    if it.get("desc"):
        body = "\n   > %s" % it["desc"].replace("\n", " ")
    if it.get("error"):
        body += "\n   ⚠️ 获取失败: %s" % it["error"]
    return line + "\n   <%s>%s" % (it.get("url", ""), body)


def build_report(items_by_key, statuses, state, today, top1=None):
    R = CFG["report"]
    papers, gh_new, gh_active, gh_watch, news = (items_by_key[k] for k in
                                                 ["paper", "gh_new", "gh_active", "gh_watch", "news"])
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
    L.append("> 采集时间：%s（本地）｜数据源：%s" % (
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        "、".join(s["name"] for s in statuses)))
    L.append("")
    ok_cnt = sum(1 for s in statuses if s["status"].startswith("OK"))
    L.append("| 维度 | 今日条目 | 说明 |")
    L.append("|---|---|---|")
    L.append("| 📄 论文雷达 | %d | arXiv 近 %d 天，按相关度排序 |" % (len(papers), CFG["arxiv"]["days"]))
    L.append("| 🌱 GitHub 新星 | %d/%d | 近 14 天新建，优先展示安全相关 |" % (len(gh_new_show), len(gh_new)))
    L.append("| 🔥 GitHub 活跃 | %d/%d | 近 7 天活跃，优先展示安全相关 |" % (len(gh_active_show), len(gh_active)))
    L.append("| ⭐ Watchlist | %d/%d | 成熟项目星标/更新动态 |" % (len(gh_watch_ok), len(CFG["github"]["watchlist"])))
    L.append("| 🛰️ 安全资讯 | %d/%d | RSS 相关度≥%d 条目 |" % (len(news_show), len(news), R["news_min_score"]))
    L.append("| ✅ 源健康度 | %d/%d | 正常采集的源数量 |" % (ok_cnt, len(statuses)))
    L.append("")

    # TL;DR
    L.append("## ⚡ 今日速览")
    L.append("")
    top_news = news_show[:3]
    top_gh = [g for g in gh_new_show if g["stars"] >= 50][:3] or gh_new_show[:2]
    top_paper = papers[:3]
    for it in top_paper:
        L.append("- 📄 **[%s](%s)**（%s，%s）" % (it["title"][:80], it["url"], it.get("date", ""), "/".join(it["tags"][:2])))
    for it in top_gh:
        L.append("- 🌱 **[%s](%s)** ⭐%s — %s" % (it["title"], it["url"], format(it["stars"], ","), it["desc"][:100]))
    for it in top_news:
        L.append("- 🛰️ **[%s](%s)**（%s）" % (it["title"][:90], it["url"], it["feed"]))
    if not (top_paper or top_gh or top_news):
        L.append("- 今日无高热度条目。")
    L.append("")

    # top1
    if top1:
        cross = "、".join(t for t in top1.get("tags", []) if t != "综合") or "单层"
        L.append("## 🏆 每日 Top1（自动评选）")
        L.append("")
        L.append(fmt_item(top1, is_new(top1), 1))
        L.append("")
        L.append("**入选理由**：相关度 %d ｜ 层级定位：%s ｜ 评选规则 = 相关度 + 跨层加成 + 新信号优先（watchlist 日常动态不参选）。"
                 % (top1.get("score", 0), cross))
        L.append("")
        L.append("<!-- top1-analysis: 分析师在此插入深度分析（是什么/技术机制/证据强度/四层定位/影响与对策） -->")
        L.append("")

    # papers
    L.append("## 📄 论文雷达（arXiv · 相关度排序）")
    L.append("")
    for i, it in enumerate(papers[:R["top_papers"]], 1):
        L.append(fmt_item(it, is_new(it), i))
        L.append("")
    if not papers:
        L.append("- 无。")
        L.append("")

    # github new
    L.append("## 🌱 GitHub 新星仓库（近 14 天创建 · 安全相关优先，按星数排序）")
    L.append("")
    for i, it in enumerate(gh_new_show, 1):
        L.append(fmt_item(it, is_new(it), i))
        L.append("")
    if not gh_new_show:
        L.append("- 无。")
        L.append("")

    # github active
    L.append("## 🔥 GitHub 活跃热点（近 7 天活跃 · 安全相关优先）")
    L.append("")
    for i, it in enumerate(gh_active_show, 1):
        L.append(fmt_item(it, is_new(it), i))
        L.append("")
    if not gh_active_show:
        L.append("- 无。")
        L.append("")

    # watchlist
    L.append("## ⭐ Watchlist 动态（成熟项目，按七日星增排序）")
    L.append("")
    for i, it in enumerate(gh_watch_ok[:R["top_gh_watch"]], 1):
        L.append(fmt_item(it, is_new(it), i))
        L.append("")

    # news
    L.append("## 🛰️ 安全资讯（近 %d 天 · 相关度过滤）" % CFG["rss_days"])
    L.append("")
    for i, it in enumerate(news_show, 1):
        L.append(fmt_item(it, is_new(it), i))
        L.append("")
    if not news_show:
        L.append("- 本期无达到阈值条目。")
        L.append("")

    # conferences
    L.append("## 🎪 会议 · 框架 · 产业动态（常设目录）")
    L.append("")
    for c in CFG["conferences"]:
        L.append("- **[%s](%s)** — %s" % (c["name"], c["url"], c["note"]))
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


# ---------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser(description="AI Agent 安全每日情报采集器")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--skip-gh", action="store_true", help="跳过 GitHub 采集")
    parser.add_argument("--skip-arxiv", action="store_true")
    parser.add_argument("--skip-rss", action="store_true")
    parser.add_argument("--json-only", action="store_true", help="只导出 JSON，不写报告")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    state = load_state()
    statuses = []
    papers, gh_new, gh_active, gh_watch, news = [], [], [], [], []

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

    items_by_key = {"paper": papers, "gh_new": gh_new, "gh_active": gh_active,
                    "gh_watch": gh_watch, "news": news}
    all_items = [it for g in items_by_key.values() for it in g]

    # Top1 评选与原文预取（预取材料存 data/top1.json，供分析师/LLM 深度分析）
    top1 = pick_top1(items_by_key)
    top1_payload = None
    if top1:
        top1_payload = dict(top1)
        top1_payload["detail"] = fetch_detail(top1)

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

    report = build_report(items_by_key, statuses, state, args.date, top1=top1)
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
    print("items: papers=%d gh_new=%d gh_active=%d watch=%d news=%d"
          % (len(papers), len(gh_new), len(gh_active), len(gh_watch), len(news)))
    for s in statuses:
        print("  [%s] %s" % (s["status"], s["name"]))


if __name__ == "__main__":
    main()
