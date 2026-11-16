def make(client, owner, topic="Gradient descent"):
    r = client.post("/api/projects", json={"topic": topic, "level": "intro", "minutes": 3}, headers=owner)
    assert r.status_code == 201, r.text
    return r.json()


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_create_then_read_back(client, owner):
    p = make(client, owner)
    assert p["status"] == "new" and p["is_owner"] is True
    got = client.get(f"/api/projects/{p['id']}", headers=owner).json()
    assert got["topic"] == "Gradient descent"
    mine = client.get("/api/projects", headers=owner).json()["projects"]
    assert p["id"] in [x["id"] for x in mine]


def test_lists_are_per_browser(client, owner, other):
    p = make(client, owner, "Only mine")
    theirs = client.get("/api/projects", headers=other).json()["projects"]
    assert p["id"] not in [x["id"] for x in theirs]


def test_anyone_with_the_link_can_watch_but_only_the_owner_can_edit(client, owner, other, example):
    p = make(client, owner)
    seen = client.get(f"/api/projects/{p['id']}", headers=other).json()
    assert seen["is_owner"] is False
    r = client.put(f"/api/projects/{p['id']}/storyboard", json={"storyboard": example}, headers=other)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "not_owner"


def test_save_storyboard_validates_and_normalizes(client, owner, example):
    p = make(client, owner)
    example["scenes"][2]["items"][0]["at"] = 99
    r = client.put(f"/api/projects/{p['id']}/storyboard", json={"storyboard": example}, headers=owner)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready" and body["title"] == example["title"]
    assert body["storyboard"]["scenes"][2]["items"][0]["at"] < 99

    example["scenes"][0]["layout"] = "hologram"
    r = client.put(f"/api/projects/{p['id']}/storyboard", json={"storyboard": example}, headers=owner)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_storyboard"


def test_missing_owner_and_bad_input_say_why(client, owner):
    r = client.post("/api/projects", json={"topic": "Physics"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_owner"
    r = client.post("/api/projects", json={"topic": "x"}, headers=owner)
    assert r.status_code == 422 and "topic" in r.json()["error"]["message"]


def test_delete(client, owner):
    p = make(client, owner)
    assert client.delete(f"/api/projects/{p['id']}", headers=owner).status_code == 204
    assert client.get(f"/api/projects/{p['id']}").status_code == 404


def test_unknown_api_route_is_json_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
