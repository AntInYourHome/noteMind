#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NebulaGraph 后端：把本地图谱（data/graph/intel_graph.db）迁移到 Nebula 并提供查询。

本机（ARM64 Windows）无法运行 Nebula 服务端——此脚本面向"远程部署"场景：
  1. 在 Linux/x86_64 服务器上：cd deploy/nebula && docker compose up -d
  2. 注册存储与建空间（首次）：
     docker compose exec nebula-console nebula-console -addr graphd -port 9669 -u root -p nebula \
       -e "ADD HOSTS \"storaged0\":9779"
  3. 本机执行迁移：py scripts/nebula_store.py --host <服务器IP> --migrate
  4. 查询：   py scripts/nebula_store.py --host <服务器IP> --recurrence / --cooccur / --neighbours X

依赖：pip install nebula3-python（已验证可装）。schema 与 SQLite 后端一一对应，
graph_store.py 继续作为本机默认后端，两者可并存。
"""
import argparse
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "graph", "intel_graph.db")

DDL = [
    "CREATE SPACE IF NOT EXISTS intel_graph (vid_type=FIXED_STRING(48), partition_num=4, replica_factor=1)",
    "USE intel_graph",
    # 点类型（Tag）
    "CREATE TAG IF NOT EXISTS item(label string, kind string, score double, url string, stars int, venue string)",
    "CREATE TAG IF NOT EXISTS kw(label string)",
    "CREATE TAG IF NOT EXISTS tag(label string)",
    "CREATE TAG IF NOT EXISTS venue(label string)",
    "CREATE TAG IF NOT EXISTS repo(label string, stars int)",
    "CREATE TAG IF NOT EXISTS day(label string)",
    # 边类型（Edge Type）
    "CREATE EDGE IF NOT EXISTS MENTIONS()",
    "CREATE EDGE IF NOT EXISTS TAGGED()",
    "CREATE EDGE IF NOT EXISTS PUBLISHED_IN()",
    "CREATE EDGE IF NOT EXISTS BELONGS_TO()",
    "CREATE EDGE IF NOT EXISTS TOP(rank int, day string)",
    "CREATE EDGE IF NOT EXISTS APPEARED_ON()",
    "CREATE EDGE IF NOT EXISTS CO_OCCUR(day string, weight double)",
]


def esc(s):
    return '"' + str(s if s is not None else "").replace("\\", "\\\\").replace('"', '\\"') + '"'


def connect(host, port=9669, user="root", password="nebula"):
    from nebula3.gclient.net import ConnectionPool
    from nebula3.Config import Config
    pool = ConnectionPool()
    conf = Config()
    assert pool.init([(host, port)], conf), "连接失败：%s:%s" % (host, port)
    sess = pool.get_session(user, password)
    return pool, sess


def wait_index_ready(sess, seconds=6):
    import time
    time.sleep(seconds)


def migrate(host, port):
    pool, sess = connect(host, port)
    print("执行 schema …")
    for stmt in DDL:
        sess.execute(stmt)
    wait_index_ready(sess)
    conn = sqlite3.connect(DB_PATH)
    nodes = conn.execute("SELECT id,type,label,props FROM node").fetchall()
    edges = conn.execute("SELECT src,dst,type,day,weight,props FROM edge").fetchall()
    conn.close()
    print("迁移节点 %d …" % len(nodes))
    tag_of = {"item": "item", "kw": "kw", "tag": "tag", "venue": "venue", "repo": "repo", "day": "day"}
    for nid, ntype, label, props_json in nodes:
        if ntype not in tag_of:
            continue
        p = json.loads(props_json or "{}")
        if ntype == "item":
            stmt = 'INSERT VERTEX item(label,kind,score,url,stars,venue) VALUES(%s,%s,%s,%s,%s,%s) WHEN NOT EXISTS' % (
                esc(label), esc(p.get("kind")), p.get("score") or 0.0, esc(p.get("url")),
                p.get("stars") or 0, esc(p.get("venue")))
        elif ntype == "repo":
            stmt = 'INSERT VERTEX repo(label,stars) VALUES(%s,%s)' % (esc(label), p.get("stars") or 0)
        else:
            stmt = "INSERT VERTEX %s(label) VALUES(%s)" % (ntype, esc(label))
        sess.execute('USE intel_graph; ' + stmt)
    print("迁移边 %d …" % len(edges))
    # 注：逐条执行（每条一次 RPC）。当前规模（千级边）秒级完成；数据量大后可改批量 INSERT。
    for src, dst, etype, day, weight, props_json in edges:
        p = json.loads(props_json or "{}")
        if etype == "TOP":
            values = "VALUES(%s,%s)" % (p.get("rank") or 0, esc(day))
        elif etype == "CO_OCCUR":
            values = "VALUES(%s,%s)" % (esc(day), weight)
        else:
            values = "VALUES()"
        sess.execute('USE intel_graph; INSERT EDGE %s %s->%s %s' % (etype, esc(src), esc(dst), values))
    print("完成。共 %d 节点 / %d 边" % (len(nodes), len(edges)))
    sess.release()
    pool.close()


def q(sess, stmt, title):
    print("\n== %s ==\n%s" % (title, stmt))
    rs = sess.execute(stmt)
    if not rs.is_succeeded():
        print("  [错误]", rs.error_msg())
        return
    cols = rs.keys()
    for i, rec in enumerate(rs):
        vals = [rec.value_at(c).cast() if hasattr(rec.value_at(c), "cast") else str(rec.value_at(c)) for c in cols]
        print("  " + " | ".join(str(v)[:52] for v in vals))
        if i >= 19:
            print("  …（截断）")
            break


def queries(host, port, which):
    pool, sess = connect(host, port)
    sess.execute("USE intel_graph")
    if "recurrence" in which:
        q(sess, 'MATCH (d:day)-[t:TOP]->(i:item) WITH i, collect(d.label) AS ds, '
                'count(ds) AS days, min(t.rank) AS best WHERE days >= 2 '
                'RETURN i.label AS 条目, days AS 在榜天数, best AS 最佳名次, ds AS 日期 '
                'ORDER BY days DESC, best ASC LIMIT 20', "跨日复现榜")
    if "cooccur" in which:
        q(sess, 'MATCH (:kw)-[c:CO_OCCUR]->(k2:kw) RETURN k2.label AS 关键词, '
                'count(c) AS 共现次数 ORDER BY 共现次数 DESC LIMIT 15', "关键词共现")
    if "neighbours" in which:
        term = which[which.index("neighbours") + 1] if len(which) > which.index("neighbours") + 1 else "safety"
        q(sess, 'MATCH (k:kw)-[m:MENTIONS]-(i:item) WHERE contains(k.label, "%s") '
                'RETURN k.label AS 实体, i.label AS 关联条目 LIMIT 20' % term,
          "邻域：%s" % term)
    sess.release()
    pool.close()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="NebulaGraph 后端（远程部署）")
    ap.add_argument("--host", required=True, help="Nebula graphd 服务器地址")
    ap.add_argument("--port", type=int, default=9669)
    ap.add_argument("--migrate", action="store_true", help="本地图谱 → Nebula 全量迁移（建 schema + 导入）")
    ap.add_argument("--recurrence", action="store_true")
    ap.add_argument("--cooccur", action="store_true")
    ap.add_argument("--neighbours", nargs="?", const="safety")
    args = ap.parse_args()
    if args.migrate:
        migrate(args.host, args.port)
    which = []
    if args.recurrence: which.append("recurrence")
    if args.cooccur: which.append("cooccur")
    if args.neighbours: which.extend(["neighbours", args.neighbours])
    if which:
        queries(args.host, args.port, which)


if __name__ == "__main__":
    main()
