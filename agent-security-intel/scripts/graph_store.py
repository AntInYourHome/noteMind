#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日情报知识图谱存储：把 latest-items.json / state.json / 历史报告沉淀为图。

图模型（零依赖，SQLite 节点/边两张表 + 递归 CTE）：
  节点: item(条目) / kw(关键词) / tag(四层标签) / venue(顶会) / repo(仓库) / day(日期)
  边:   item-MENTIONS->kw (共现来源)   item-TAGGED->tag
        item-PUBLISHED_IN->venue        item-BELONGS_TO->repo
        day-TOP{rank}->item (榜单)      item-APPEARED_ON->day (采集见)
用法:
  py scripts/graph_store.py                 # 追加/覆盖当日图谱（幂等）
  py scripts/graph_store.py --rebuild       # 清空后重建（当日全量 + 历史报告 Top10 回填）
  py scripts/graph_store.py --stats         # 图规模统计
  py scripts/graph_store.py --cooccur [N]   # 关键词共现 TOP-N（全期）
  py scripts/graph_store.py --recurrence    # 跨日复现条目（榜单赢家）
  py scripts/graph_store.py --neighbours X  # 某实体邻域（按标签/关键词/标题模糊）
  py scripts/graph_store.py --export        # 导出 data/graph/graph.json（可视化用）
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEMS_PATH = os.path.join(ROOT, "data", "latest-items.json")
STATE_PATH = os.path.join(ROOT, "data", "state.json")
REPORT_DIR = os.path.join(ROOT, "reports")
DB_PATH = os.path.join(ROOT, "data", "graph", "intel_graph.db")
EXPORT_PATH = os.path.join(ROOT, "data", "graph", "graph.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS node (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, label TEXT, props TEXT);
CREATE TABLE IF NOT EXISTS edge (
  src TEXT NOT NULL, dst TEXT NOT NULL, type TEXT NOT NULL, day TEXT,
  weight REAL DEFAULT 1, props TEXT,
  PRIMARY KEY (src, dst, type, day));
CREATE INDEX IF NOT EXISTS idx_edge_src ON edge(src, type);
CREATE INDEX IF NOT EXISTS idx_edge_dst ON edge(dst, type);
CREATE INDEX IF NOT EXISTS idx_edge_day ON edge(day);
"""


def _nid(prefix, key):
    return prefix + ":" + hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:16]


def open_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def put_node(conn, nid, ntype, label, props=None):
    conn.execute("INSERT OR REPLACE INTO node VALUES (?,?,?,?)",
                 (nid, ntype, label, json.dumps(props or {}, ensure_ascii=False)))


def put_edge(conn, src, dst, etype, day, weight=1, props=None):
    conn.execute("INSERT OR REPLACE INTO edge VALUES (?,?,?,?,?,?)",
                 (src, dst, etype, day, weight, json.dumps(props or {}, ensure_ascii=False)))


def load_day(conn, items, day):
    """一个采集日的全部条目入图（重跑同日 = 覆盖，幂等）。"""
    conn.execute("DELETE FROM edge WHERE day=?", (day,))
    put_node(conn, "day:" + day, "day", day)
    for it in items:
        url = it.get("url") or ""
        title = (it.get("title") or "?").strip()
        iid = _nid("item", url or title)
        put_node(conn, iid, "item", title, {
            "kind": it.get("kind"), "score": it.get("score"),
            "url": url, "date": it.get("date"), "stars": it.get("stars"),
            "venue": it.get("venue", ""), "feed": it.get("feed", ""),
        })
        put_edge(conn, iid, "day:" + day, "APPEARED_ON", day)
        kws = it.get("hits") or []
        k_nodes = []
        for kw in kws:
            kid = _nid("kw", kw.lower())
            put_node(conn, kid, "kw", kw)
            put_edge(conn, iid, kid, "MENTIONS", day)
            k_nodes.append(kid)
        # 同一条目内的关键词两两共现（无序对，去重后入库）
        for a in range(len(k_nodes)):
            for b in range(a + 1, len(k_nodes)):
                x, y = sorted((k_nodes[a], k_nodes[b]))
                put_edge(conn, x, y, "CO_OCCUR", day, 1)
        for tag in it.get("tags") or []:
            tid = _nid("tag", tag)
            put_node(conn, tid, "tag", tag)
            put_edge(conn, iid, tid, "TAGGED", day)
        if it.get("venue"):
            vid = _nid("venue", it["venue"])
            put_node(conn, vid, "venue", it["venue"])
            put_edge(conn, iid, vid, "PUBLISHED_IN", day)
        kind = it.get("kind") or ""
        if kind.startswith("gh") or kind == "deep_read":
            repo = title.split()[0] if kind == "deep_read" else title
            if "/" in repo:
                rid = _nid("repo", repo)
                put_node(conn, rid, "repo", repo, {"stars": it.get("stars")})
                put_edge(conn, iid, rid, "BELONGS_TO", day)


TOP_LINE = re.compile(
    r"^(\d+)\.\s+\S+\s+\[([^\]]+)\]\s+(.+?)\s+—\s+(.*)$", re.M)


def backfill_reports(conn):
    """从历史报告的 Top10 榜单行回填 day-TOP->item 边（09-09 起的新格式）。"""
    days = 0
    edges = 0
    for fn in sorted(os.listdir(REPORT_DIR)):
        m = re.match(r"intel-(\d{4}-\d{2}-\d{2})\.md$", fn)
        if not m:
            continue
        day = m.group(1)
        put_node(conn, "day:" + day, "day", day)
        txt = open(os.path.join(REPORT_DIR, fn), encoding="utf-8").read()
        for mm in TOP_LINE.finditer(txt):
            rank, tags, title = int(mm.group(1)), mm.group(2), mm.group(3).strip()
            if rank > 10:
                continue
            iid = _nid("item", title)
            put_node(conn, iid, "item", title, {"from_report": day})
            for tag in tags.split("/"):
                tid = _nid("tag", tag.strip())
                put_node(conn, tid, "tag", tag.strip())
                put_edge(conn, iid, tid, "TAGGED", day)
            put_edge(conn, "day:" + day, iid, "TOP", day, rank, {"rank": rank})
            edges += 1
        days += 1
    return days, edges


def load_today(conn):
    data = json.load(open(ITEMS_PATH, encoding="utf-8"))
    load_day(conn, data.get("items", []), data["date"])
    return data["date"], len(data.get("items", []))


# ---------------------------------------------------------------- queries
def q_stats(conn):
    for row in conn.execute("SELECT type, COUNT(*) FROM node GROUP BY type ORDER BY 2 DESC"):
        print("  node %-8s %6d" % row)
    print()
    for row in conn.execute("SELECT type, COUNT(*) FROM edge GROUP BY type ORDER BY 2 DESC"):
        print("  edge %-14s %6d" % row)


def q_cooccur(conn, n=15):
    print("== 关键词共现 TOP%d（注：共现边自本日数据起累积，历史报告无逐条关键词）==" % n)
    q = """SELECT na.label, nb.label, COUNT(DISTINCT e.day) days, SUM(e.weight) tot
           FROM edge e JOIN node na ON e.src=na.id JOIN node nb ON e.dst=nb.id
           WHERE e.type='CO_OCCUR' GROUP BY e.src, e.dst
           ORDER BY tot DESC, days DESC LIMIT ?"""
    for a, b, days, tot in conn.execute(q, (n,)):
        print("  %-26s × %-26s %d天 累计×%d" % (a, b, days, tot))


def q_recurrence(conn, min_days=2):
    print("== 跨日复现条目（TOP 榜单出现 ≥%d 天；APPEARED_ON 自本日起累积）==" % min_days)
    q = """SELECT n.label, COUNT(DISTINCT e.day) days, GROUP_CONCAT(DISTINCT e.day) ds,
                  MIN(CAST(json_extract(e.props,'$.rank') AS INT)) best
           FROM edge e JOIN node n ON e.dst=n.id
           WHERE e.type='TOP' AND n.type='item'
           GROUP BY e.dst HAVING days>=? ORDER BY days DESC, best ASC LIMIT 25"""
    for label, days, ds, best in conn.execute(q, (min_days,)):
        print("  %2d天 | 最佳第%d名 | %-46s | %s" % (days, best or 0, (label or "")[:46], ds))


def q_neighbours(conn, term):
    like = "%" + term.lower() + "%"
    seeds = [r[0] for r in conn.execute(
        "SELECT id FROM node WHERE type IN ('kw','tag','repo','venue') "
        "AND lower(COALESCE(label,'')) LIKE ? LIMIT 5", (like,))]
    if not seeds:
        print("无匹配实体:", term)
        return
    for sid in seeds:
        row = conn.execute("SELECT type,label FROM node WHERE id=?", (sid,)).fetchone()
        print("\n== %s [%s] 的邻域 ==" % (row[1], row[0]))
        q = """SELECT n.type, n.label, e.type, MAX(e.day)
               FROM edge e JOIN node n ON (e.src=? AND e.dst=n.id) OR (e.dst=? AND e.src=n.id)
               JOIN node self ON self.id=?
               WHERE n.id != self.id GROUP BY n.id ORDER BY 4 DESC LIMIT 20"""
        for ntype, label, etype, day in conn.execute(q, (sid, sid, sid)):
            print("  --%s--> %s[%s] (至 %s)" % (etype, (label or "")[:52], ntype, day))


def export_json(conn):
    nodes = [{"id": r[0], "type": r[1], "label": r[2], **json.loads(r[3] or "{}")}
             for r in conn.execute("SELECT * FROM node")]
    edges = [{"src": r[0], "dst": r[1], "type": r[2], "day": r[3], "weight": r[4]}
             for r in conn.execute("SELECT src,dst,type,day,weight FROM edge")]
    os.makedirs(os.path.dirname(EXPORT_PATH), exist_ok=True)
    json.dump({"nodes": nodes, "edges": edges},
              open(EXPORT_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    print("export -> %s (%d nodes, %d edges)" % (EXPORT_PATH, len(nodes), len(edges)))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = sys.argv[1:]
    conn = open_db()
    if "--rebuild" in args:
        conn.execute("DELETE FROM node"); conn.execute("DELETE FROM edge")
        d, n = load_today(conn)
        print("当日 %s 入图 %d 条目" % (d, n))
        days, edges = backfill_reports(conn)
        print("历史回填 %d 天报告，TOP 边 %d 条" % (days, edges))
        conn.commit()
    elif not any(a.startswith("--") for a in args):
        d, n = load_today(conn)
        backfill_reports(conn)
        conn.commit()
        print("graph upsert: %s, %d items" % (d, n))
    if "--stats" in args:
        q_stats(conn)
    if "--cooccur" in args:
        q_cooccur(conn, int(args[args.index("--cooccur") + 1]) if len(args) > args.index("--cooccur") + 1 and args[args.index("--cooccur") + 1].isdigit() else 15)
    if "--recurrence" in args:
        q_recurrence(conn)
    if "--neighbours" in args:
        i = args.index("--neighbours")
        if i + 1 < len(args):
            q_neighbours(conn, args[i + 1])
    if "--export" in args:
        export_json(conn)
    conn.close()


if __name__ == "__main__":
    main()
