#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Neo4j 后端：本地图谱（data/graph/intel_graph.db）→ Neo4j 迁移 + Cypher 查询。

部署事实（本机，2026-09-14 验证）：
  - MS OpenJDK 21 aarch64: C:\\tools\\jdk-21.0.12.1+1
  - Neo4j Community 5.26.0: C:\\tools\\neo4j-community-5.26.0（bolt://127.0.0.1:7687, neo4j/intelgraph2026）
  - 启动: cd /c/tools/neo4j-community-5.26.0 && JAVA_HOME="C:\\tools\\jdk-21.0.12.1+1" ./bin/neo4j.bat console
用法:
  py scripts/neo4j_store.py --migrate            # SQLite 图 → Neo4j 全量迁移（MERGE 幂等）
  py scripts/neo4j_store.py --recurrence         # 跨日复现榜
  py scripts/neo4j_store.py --cooccur [N]        # 关键词共现
  py scripts/neo4j_store.py --neighbours safety  # 邻域查询
依赖：pip install neo4j
"""
import argparse
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "graph", "intel_graph.db")
URI, USER, PASSWORD = "bolt://127.0.0.1:7687", "neo4j", "intelgraph2026"

INDEX_DDL = [
    "CREATE INDEX item_label IF NOT EXISTS FOR (n:item) ON (n.label)",
    "CREATE INDEX kw_label IF NOT EXISTS FOR (n:kw) ON (n.label)",
    "CREATE INDEX tag_label IF NOT EXISTS FOR (n:tag) ON (n.label)",
    "CREATE INDEX repo_label IF NOT EXISTS FOR (n:repo) ON (n.label)",
]


def driver():
    from neo4j import GraphDatabase
    return GraphDatabase.driver(URI, auth=(USER, PASSWORD))


def migrate():
    conn = sqlite3.connect(DB_PATH)
    nodes = conn.execute("SELECT id,type,label,props FROM node").fetchall()
    edges = conn.execute("SELECT src,dst,type,day,weight,props FROM edge").fetchall()
    conn.close()
    d = driver()
    with d.session() as s:
        for stmt in INDEX_DDL:
            s.run(stmt)
        print("迁移节点 %d …" % len(nodes))
        tag_of = {"item": "item", "kw": "kw", "tag": "tag", "venue": "venue",
                  "repo": "repo", "day": "day"}
        for nid, ntype, label, props_json in nodes:
            if ntype not in tag_of:
                continue
            p = json.loads(props_json or "{}")
            s.run(
                "MERGE (n:%s {id: $id}) SET n.label = $label, "
                "n.kind = coalesce($kind, n.kind), n.score = coalesce($score, n.score), "
                "n.url = coalesce($url, n.url), n.stars = coalesce($stars, n.stars), "
                "n.venue = coalesce($venue, n.venue)" % ntype,
                id=nid, label=label or "", kind=p.get("kind"), score=p.get("score"),
                url=p.get("url"), stars=p.get("stars"), venue=p.get("venue"))
        print("迁移边 %d …" % len(edges))
        for src, dst, etype, day, weight, props_json in edges:
            p = json.loads(props_json or "{}")
            extra = {"TOP": ", r.rank = $rank", "CO_OCCUR": ", r.weight = $weight"}.get(etype, "")
            s.run(
                "MATCH (a {id:$src}), (b {id:$dst}) "
                "MERGE (a)-[r:%s {day: $day}]->(b) SET r.day = $day%s" % (etype, extra),
                src=src, dst=dst, day=day, rank=p.get("rank"), weight=weight)
        cnt = s.run("MATCH (n) RETURN count(n) AS n").single()["n"]
        rel = s.run("MATCH ()-[r]->() RETURN count(r) AS r").single()["r"]
    d.close()
    print("完成：Neo4j 现 %d 节点 / %d 关系" % (cnt, rel))


def rows(sess, q, title, **kw):
    print("\n== %s ==" % title)
    for i, rec in enumerate(sess.run(q, **kw)):
        print("  " + " | ".join(str(v)[:56] for v in rec.values()))
        if i >= 19:
            print("  …（截断）")
            break


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--migrate", action="store_true")
    ap.add_argument("--recurrence", action="store_true")
    ap.add_argument("--cooccur", nargs="?", type=int, const=15)
    ap.add_argument("--neighbours", nargs="?", const="safety")
    a = ap.parse_args()
    if a.migrate:
        migrate()
    d = driver()
    with d.session() as s:
        if a.recurrence:
            rows(s, """MATCH (d:day)-[t:TOP]->(i:item)
                WITH i, collect(DISTINCT d.id) AS ds, count(DISTINCT d.id) AS days, min(t.rank) AS best
                WHERE days >= 2
                RETURN i.label AS 条目, days AS 在榜天数, best AS 最佳名次, ds AS 日期
                ORDER BY days DESC, best ASC LIMIT 20""", "跨日复现榜")
        if a.cooccur:
            rows(s, """MATCH (a:kw)-[c:CO_OCCUR]->(b:kw)
                RETURN a.label AS 关键词A, b.label AS 关键词B,
                       count(DISTINCT c.day) AS 天数, sum(c.weight) AS 累计
                ORDER BY 累计 DESC, 天数 DESC LIMIT $n""", "关键词共现", n=a.cooccur)
        if a.neighbours:
            rows(s, """MATCH (x)-[r]-(y) WHERE x.label CONTAINS $t
                RETURN labels(x)[0] AS 类型, x.label AS 实体, type(r) AS 关系,
                       labels(y)[0] AS 对端类型, y.label AS 对端 LIMIT 25""",
                "邻域：%s" % a.neighbours, t=a.neighbours)
    d.close()


if __name__ == "__main__":
    main()
