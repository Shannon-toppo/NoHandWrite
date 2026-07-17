import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from nohandwrite.store import Store
    import server.main as main
    importlib.reload(main)
    monkeypatch.setattr(main, "store", Store(tmp_path))
    return TestClient(main.app)


def sample_body(writer="taro", char="木"):
    return {
        "writer": writer, "char": char, "device": "test", "canvas": [450, 450],
        "strokes": [[{"x": 1, "y": 2, "t": 0, "p": 0.5}, {"x": 3, "y": 4, "t": 10, "p": 0.4}]],
    }


def test_prompts(client):
    sets = client.get("/api/prompts").json()
    assert "style" in sets and "hiragana" in sets and "alnum" in sets
    assert len(sets["hiragana"]["chars"]) == 71
    assert len(sets["alnum"]["chars"]) == 62


def test_save_and_fetch(client):
    r = client.post("/api/samples", json=sample_body())
    assert r.status_code == 200
    assert r.json() == {"char": "木", "count": 1}
    r = client.post("/api/samples", json=sample_body())
    assert r.json()["count"] == 2

    r = client.get("/api/writers/taro/summary")
    assert r.json()["chars"] == {"木": 2}

    r = client.get("/api/writers/taro/chars/木")
    assert r.status_code == 200
    body = r.json()
    assert body["codepoint"] == "U+6728"
    assert len(body["samples"]) == 2

    r = client.post("/api/samples/undo", json={"writer": "taro", "char": "木"})
    assert r.json()["count"] == 1


def test_validation(client):
    bad = sample_body(char="木木")
    assert client.post("/api/samples", json=bad).status_code == 422
    bad = sample_body(writer="../x")
    assert client.post("/api/samples", json=bad).status_code == 422
    assert client.get("/api/writers/taro/chars/未").status_code == 404
