"""Samba 任务目录：用内存 fake 文件系统打桩 smbfs 原语，验证 complete.txt 判定与文件读写。"""
from types import SimpleNamespace

from app.modules.samba import smbfs


def _install_fake(monkeypatch):
    state = {"dirs": set(), "files": {}, "complete": {}}

    def listdir(task=""):
        if task == "":
            return sorted(state["dirs"])
        names = {f for (t, f) in state["files"] if t == task}
        if task in state["complete"]:
            names.add("complete.txt")
        return sorted(names)

    def stat(task="", file=None):
        if file == "complete.txt":
            return SimpleNamespace(st_size=0, st_mtime=state["complete"][task], isdir=False)
        if file is None:
            return SimpleNamespace(st_size=0, st_mtime=1693700000.0, isdir=True)
        return SimpleNamespace(st_size=len(state["files"][(task, file)]), st_mtime=1693700000.0, isdir=False)

    def exists(task, file=None):
        if file is None:
            return task == "" or task in state["dirs"]
        if file == "complete.txt":
            return task in state["complete"]
        return (task, file) in state["files"]

    monkeypatch.setattr(smbfs, "listdir", listdir)
    monkeypatch.setattr(smbfs, "stat", stat)
    monkeypatch.setattr(smbfs, "exists", exists)
    monkeypatch.setattr(smbfs, "read", lambda t, f: state["files"][(t, f)])
    monkeypatch.setattr(smbfs, "write", lambda t, f, d: state["files"].__setitem__((t, f), d))
    monkeypatch.setattr(smbfs, "mkdir", lambda t: state["dirs"].add(t))
    monkeypatch.setattr(smbfs, "remove", lambda t, f: state["complete"].pop(t, None) if f == "complete.txt" else state["files"].pop((t, f)))
    monkeypatch.setattr(smbfs, "is_dir", lambda st: getattr(st, "isdir", False))
    # write 对 complete.txt 需同时落 complete 时间戳
    orig_write = state["files"]

    def write(t, f, d):
        orig_write[(t, f)] = d
        if f == "complete.txt":
            state["complete"][t] = 1756900000.0

    monkeypatch.setattr(smbfs, "write", write)
    return state


def test_task_lifecycle_with_complete_marker(client, admin, monkeypatch):
    _install_fake(monkeypatch)

    # 初始为空
    assert client.get("/api/tools/samba/tasks", headers=admin).json()["total"] == 0

    # 新建任务 → 未完成
    r = client.post("/api/tools/samba/tasks", json={"name": "任务A"}, headers=admin)
    assert r.status_code == 200
    body = client.get("/api/tools/samba/tasks", headers=admin).json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "任务A" and body["items"][0]["done"] is False

    # 上传文件 → 可见、可下载
    r = client.post(
        "/api/tools/samba/tasks/任务A/files",
        files={"file": ("data.csv", b"a,b\n1,2\n", "text/csv")},
        headers=admin,
    )
    assert r.status_code == 200
    files = client.get("/api/tools/samba/tasks/任务A/files", headers=admin).json()
    assert files["total"] == 1 and files["items"][0]["name"] == "data.csv"
    assert files["items"][0]["size"] == 8
    r = client.get(
        "/api/tools/samba/tasks/任务A/download",
        params={"file": "data.csv"},
        headers=admin,
    )
    assert r.status_code == 200 and r.content == b"a,b\n1,2\n"

    # 标记完成 → complete.txt 出现，状态翻转
    r = client.post("/api/tools/samba/tasks/任务A/complete", headers=admin)
    assert r.json()["done"] is True
    body = client.get("/api/tools/samba/tasks", headers=admin).json()
    assert body["items"][0]["done"] is True and body["items"][0]["complete_time"]

    # 取消完成 → 回到未完成
    client.delete("/api/tools/samba/tasks/任务A/complete", headers=admin)
    assert client.get("/api/tools/samba/tasks", headers=admin).json()["items"][0]["done"] is False


def test_duplicate_task_rejected(client, admin, monkeypatch):
    _install_fake(monkeypatch)
    client.post("/api/tools/samba/tasks", json={"name": "t1"}, headers=admin)
    r = client.post("/api/tools/samba/tasks", json={"name": "t1"}, headers=admin)
    assert r.status_code == 400


def test_unsafe_names_rejected(client, admin, monkeypatch):
    _install_fake(monkeypatch)
    for bad in ["..", "a/b", "a\\b", ""]:
        r = client.post("/api/tools/samba/tasks", json={"name": bad}, headers=admin)
        assert r.status_code == 400, bad
    r = client.get("/api/tools/samba/tasks/../etc/files", headers=admin)
    assert r.status_code in (400, 404)


def test_missing_task_404(client, admin, monkeypatch):
    _install_fake(monkeypatch)
    assert client.get("/api/tools/samba/tasks/nope/files", headers=admin).status_code == 404


def test_samba_requires_auth(client):
    assert client.get("/api/tools/samba/tasks").status_code == 401


# ---------- 数据库状态记录 ----------

def test_status_recorded_in_db(client, admin, monkeypatch):
    _install_fake(monkeypatch)

    # 建任务 → 镜像 + created 事件
    client.post("/api/tools/samba/tasks", json={"name": "任务C"}, headers=admin)
    mirror = client.get("/api/tools/samba/db/tasks", headers=admin).json()
    row = mirror["items"][0]
    assert row["task_name"] == "任务C" and row["done"] is False and row["files_count"] == 0

    # 上传 → upload 事件（含文件名）
    client.post(
        "/api/tools/samba/tasks/任务C/files",
        files={"file": ("f.txt", b"hello", "text/plain")},
        headers=admin,
    )
    events = client.get("/api/tools/samba/db/events", params={"task": "任务C"}, headers=admin).json()
    kinds = [e["event"] for e in reversed(events["items"])]
    assert kinds[:2] == ["created", "upload"]
    assert events["items"][0]["file"] == "f.txt" and events["items"][0]["username"] == "admin"

    # 标记完成 → 镜像翻转为完成；取消 → 回落
    client.post("/api/tools/samba/tasks/任务C/complete", headers=admin)
    row = next(r for r in client.get("/api/tools/samba/db/tasks", headers=admin).json()["items"]
               if r["task_name"] == "任务C")
    assert row["done"] is True and row["complete_time"] and row["files_count"] == 1
    client.delete("/api/tools/samba/tasks/任务C/complete", headers=admin)
    row = next(r for r in client.get("/api/tools/samba/db/tasks", headers=admin).json()["items"]
               if r["task_name"] == "任务C")
    assert row["done"] is False and row["files_count"] == 1  # 文件计数不被清掉

    # 事件流水完整
    kinds = [e["event"] for e in reversed(
        client.get("/api/tools/samba/db/events", params={"task": "任务C"}, headers=admin).json()["items"]
    )]
    assert kinds == ["created", "upload", "complete", "undo_complete"]


def test_list_syncs_mirror(client, admin, monkeypatch):
    _install_fake(monkeypatch)
    client.post("/api/tools/samba/tasks", json={"name": "任务D"}, headers=admin)
    client.post(
        "/api/tools/samba/tasks/任务D/files",
        files={"file": ("x.bin", b"12345", "application/octet-stream")},
        headers=admin,
    )
    client.get("/api/tools/samba/tasks", headers=admin)  # 列表访问触发同步
    row = next(r for r in client.get("/api/tools/samba/db/tasks", headers=admin).json()["items"]
               if r["task_name"] == "任务D")
    assert row["files_count"] == 1


def test_samba_tables_visible_in_tools_info(client, admin):
    tools = client.get("/api/tools", headers=admin).json()
    samba = next(t for t in tools if t["name"] == "samba")
    assert set(samba["tables"]) == {"samba_tasks", "samba_events"}
