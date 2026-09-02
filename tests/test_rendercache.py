from nohandwrite.rendercache import RenderCache


def test_round_trips_through_memory_and_disk(tmp_path):
    cache = RenderCache(tmp_path)
    cache.put("taro", "g1-u7af9-abc", {"mode": "generated", "strokes": [[[0, 0]]]})
    assert cache.get("taro", "g1-u7af9-abc")["mode"] == "generated"
    # a fresh instance reads the same entry back off disk
    assert RenderCache(tmp_path).get("taro", "g1-u7af9-abc") is not None
    assert cache.get("taro", "g1-u7af9-other") is None
    assert cache.get("jiro", "g1-u7af9-abc") is None


def test_memory_only_cache_never_touches_disk(tmp_path):
    cache = RenderCache(None)
    cache.put("taro", "b-u6728-abc", {"mode": "smooth"})
    assert cache.get("taro", "b-u6728-abc") == {"mode": "smooth"}
    assert not list(tmp_path.iterdir())


def test_memory_bound_falls_back_to_disk(tmp_path):
    cache = RenderCache(tmp_path, memory_entries=2)
    for i in range(5):
        cache.put("taro", f"b-u{i:04x}-abc", {"i": i})
    assert len(cache._mem) == 2
    assert cache.get("taro", "b-u0000-abc") == {"i": 0}      # evicted, on disk


def test_clear_one_writer_and_all(tmp_path):
    cache = RenderCache(tmp_path)
    cache.put("taro", "b-u6728-a", {"i": 1})
    cache.put("jiro", "b-u6728-a", {"i": 2})
    assert cache.clear("taro") == 1
    assert cache.get("taro", "b-u6728-a") is None
    assert cache.get("jiro", "b-u6728-a") == {"i": 2}
    assert cache.clear() == 1
    assert cache.get("jiro", "b-u6728-a") is None


def test_rejects_unsafe_writer_and_key_names(tmp_path):
    """Keys become file names, so a traversal attempt must not reach disk."""
    cache = RenderCache(tmp_path)
    cache.put("../etc", "b-u6728-a", {"i": 1})
    cache.put("taro", "../../escape", {"i": 1})
    assert not list(tmp_path.rglob("*.json"))
    # the memory level still works, so nothing silently loses data
    assert cache.get("taro", "../../escape") == {"i": 1}


def test_prunes_the_oldest_files_past_the_disk_bound(tmp_path):
    cache = RenderCache(tmp_path, disk_entries=8)
    for i in range(64):
        cache.put("taro", f"b-u{i:04x}-abc", {"i": i})
    assert len(list((tmp_path / "taro").glob("*.json"))) <= 8
