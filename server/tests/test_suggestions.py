"""改进意见：提交校验（100字/特殊字符）、本人列表、管理面可见性。"""


def test_submit_ok(client, admin):
    r = client.post(
        "/api/tools/suggestions",
        json={"content": "希望日志解析支持 gzip 压缩包上传！"},
        headers=admin,
    )
    assert r.status_code == 200
    assert r.json()["id"] == 1


def test_submit_too_long(client, admin):
    r = client.post(
        "/api/tools/suggestions",
        json={"content": "长" * 101},
        headers=admin,
    )
    assert r.status_code == 400


def test_submit_special_chars_rejected(client, admin):
    for bad in ["加个@功能", "<script>alert(1)</script>", "a&b", "你好#"]:
        r = client.post("/api/tools/suggestions", json={"content": bad}, headers=admin)
        assert r.status_code == 400, bad


def test_submit_blank_rejected(client, admin):
    assert client.post(
        "/api/tools/suggestions", json={"content": "   "}, headers=admin
    ).status_code == 400


def test_boundary_100_chars_ok(client, admin):
    r = client.post(
        "/api/tools/suggestions", json={"content": "好" * 100}, headers=admin
    )
    assert r.status_code == 200


def test_my_list_only_own(client, admin, business):
    client.post(
        "/api/tools/suggestions", json={"content": "管理员的建议"}, headers=admin
    )
    client.post(
        "/api/tools/suggestions", json={"content": "业务用户的建议"}, headers=business
    )
    mine = client.get("/api/tools/suggestions", headers=business).json()
    assert mine["total"] == 1
    assert mine["items"][0]["content"] == "业务用户的建议"


def test_admin_can_see_all_via_data_mgmt(client, admin, business):
    client.post(
        "/api/tools/suggestions", json={"content": "建议A"}, headers=admin
    )
    client.post(
        "/api/tools/suggestions", json={"content": "建议B"}, headers=business
    )
    r = client.get("/api/admin/data/suggestions/suggestions", headers=admin)
    assert r.status_code == 200
    assert r.json()["total"] == 2
