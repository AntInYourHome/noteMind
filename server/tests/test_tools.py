"""工具模块：发现机制与三个内置工具。"""

EXPECTED_TOOLS = {"notes", "log_parser", "arm_registers"}


def test_tools_discovery(client, admin):
    r = client.get("/api/tools", headers=admin)
    assert r.status_code == 200
    names = {t["name"] for t in r.json()}
    assert EXPECTED_TOOLS <= names
    notes = next(t for t in r.json() if t["name"] == "notes")
    assert notes["tables"] == {"notes": "备忘录", "note_categories": "分类"}
    # 欢迎首页依赖的元信息（icon/desc/usage）
    for t in r.json():
        assert t["icon"] and t["desc"] and t["usage"], t["name"]


def test_tools_requires_auth(client):
    assert client.get("/api/tools").status_code == 401


def test_notes_crud_flow(client, admin):
    r = client.post(
        "/api/tools/notes",
        json={"title": "t1", "content": "c1"},
        headers=admin,
    )
    assert r.status_code == 200
    note_id = r.json()["id"]

    r = client.get("/api/tools/notes", params={"keyword": "t1"}, headers=admin)
    assert r.json()["total"] == 1

    r = client.put(
        f"/api/tools/notes/{note_id}",
        json={"title": "t1x", "content": "c1x"},
        headers=admin,
    )
    assert r.json()["title"] == "t1x"

    assert client.delete(f"/api/tools/notes/{note_id}", headers=admin).status_code == 200
    r = client.get("/api/tools/notes", headers=admin)
    assert r.json()["total"] == 0


def test_log_parser_analyze(client, admin):
    text = "\n".join(
        [
            "2026-09-03 10:00:01 INFO start",
            "2026-09-03 10:00:02 ERROR connect to 10.0.0.1:5432 failed after 3 retries",
            "2026-09-03 10:00:03 ERROR connect to 10.0.0.2:5432 failed after 5 retries",
        ]
    )
    r = client.post("/api/tools/log_parser/analyze", data={"text": text}, headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["total_lines"] == 3
    assert body["levels"]["ERROR"] == 2
    # 两条同类错误应聚成一组
    assert body["error_groups"][0]["count"] == 2
    assert body["first_timestamp"].startswith("2026-09-03")


def test_log_parser_empty_input(client, admin):
    r = client.post("/api/tools/log_parser/analyze", data={"text": ""}, headers=admin)
    assert r.status_code == 400


def test_arm_registers_search(client, admin):
    r = client.get("/api/tools/arm_registers", params={"keyword": "SCTLR"}, headers=admin)
    assert r.json()["total"] == 2

    r = client.get("/api/tools/arm_registers", params={"klass": "PSTATE"}, headers=admin)
    assert all(item["klass"] == "PSTATE" for item in r.json()["items"])

    r = client.get("/api/tools/arm_registers/classes", headers=admin)
    assert "系统寄存器" in r.json()
