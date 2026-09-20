from eryou_assistant.core.guides import GuideStore, normalize_url


def test_normalize_url_and_persist_collections(tmp_path) -> None:
    path = tmp_path / "guides.json"
    store = GuideStore(path)

    assert normalize_url("example.com/path#part") == "https://example.com/path"
    assert store.toggle_bookmark("示例", "example.com/path") is True
    assert store.is_bookmarked("https://example.com/path")
    store.record_visit("示例", "https://example.com/path")
    store.record_visit("新标题", "https://example.com/path")
    store.update_last_title("https://example.com/path", "最终标题")

    restored = GuideStore(path)
    assert [item.title for item in restored.bookmarks] == ["示例"]
    assert len(restored.history) == 1
    assert restored.history[0].title == "最终标题"


def test_history_keeps_non_adjacent_navigation(tmp_path) -> None:
    store = GuideStore(tmp_path / "guides.json")
    store.record_visit("A", "https://a.example")
    store.record_visit("B", "https://b.example")
    store.record_visit("A", "https://a.example")
    assert [item.title for item in store.history] == ["A", "B", "A"]
