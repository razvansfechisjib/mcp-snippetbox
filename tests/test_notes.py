"""Tool-level tests: these call the functions the MCP tools wrap."""
import importlib
import sys

import pytest


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    """Import server.py against a throwaway notes file."""
    monkeypatch.setenv("MCP_NOTES_FILE", str(tmp_path / "notes.json"))
    sys.modules.pop("server", None)
    return importlib.import_module("server")


def test_add_then_get_round_trips(srv):
    srv.add_note("hello", "world")
    assert srv.get_note("hello")["body"] == "world"


def test_missing_note_raises(srv):
    with pytest.raises(srv.NoteNotFound):
        srv.get_note("nope")


def test_duplicate_title_is_refused(srv):
    srv.add_note("dup", "first")
    with pytest.raises(ValueError):
        srv.add_note("dup", "second")
    assert srv.get_note("dup")["body"] == "first"


def test_overwrite_keeps_created(srv):
    first = srv.add_note("k", "a")
    again = srv.add_note("k", "b", overwrite=True)
    assert again["created"] == first["created"]
    assert srv.get_note("k")["body"] == "b"


def test_update_and_delete(srv):
    srv.add_note("t", "a")
    srv.update_note("t", "b")
    assert srv.get_note("t")["body"] == "b"
    srv.delete_note("t")
    with pytest.raises(srv.NoteNotFound):
        srv.get_note("t")


def test_list_is_searchable_and_structured(srv):
    srv.add_note("groceries", "milk and eggs")
    srv.add_note("ideas", "write more tests")
    out = srv.list_notes(query="MILK")
    assert out["total"] == 1
    assert out["notes"][0]["title"] == "groceries"
    assert out["notes"][0]["updated"]


def test_list_is_newest_first(srv):
    srv.add_note("old", "1")
    srv.add_note("new", "2")
    titles = [n["title"] for n in srv.list_notes()["notes"]]
    assert titles == ["new", "old"]


def test_non_ascii_stays_readable(srv, tmp_path):
    srv.add_note("中文", "笔记内容")
    raw = (tmp_path / "notes.json").read_text(encoding="utf-8")
    assert "笔记内容" in raw
