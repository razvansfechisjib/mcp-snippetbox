"""notes-box: a small MCP server that exposes personal notes as tools.

Run it directly (stdio transport) or point Claude Desktop at it; see README.
"""
import argparse
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("notes-box")

# Configurable so tests and multiple instances do not fight over one file.
NOTES = Path(os.environ.get("MCP_NOTES_FILE", Path.home() / ".mcp_notes.json"))

# add/update/delete do read-modify-write, so they need to be serialised.
_lock = threading.Lock()


class NoteNotFound(Exception):
    """Raised when a title is not present in the store."""


def _now():
    # Microsecond precision: two notes written in the same second must still
    # sort deterministically.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _load():
    if not NOTES.exists():
        return {}
    try:
        with NOTES.open(encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        # Never silently overwrite data we failed to parse: park it instead.
        NOTES.replace(NOTES.with_suffix(".corrupt"))
        return {}


def _save(data):
    """Write atomically: a crash mid-write must not truncate the store."""
    NOTES.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(NOTES.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, NOTES)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@mcp.tool()
def add_note(title: str, body: str, overwrite: bool = False) -> dict:
    """Save a new note under a title.

    Args:
        title: unique key for the note.
        body: note text, stored verbatim.
        overwrite: allow replacing an existing note with the same title.
            Defaults to False so a duplicate title cannot destroy data.

    Returns:
        The stored title with its created/updated timestamps.

    Raises:
        ValueError: the title exists and overwrite was not requested.
    """
    with _lock:
        data = _load()
        if title in data and not overwrite:
            raise ValueError(
                "note %r already exists; pass overwrite=true to replace it"
                % title)
        created = data.get(title, {}).get("created") or _now()
        stamp = _now()
        data[title] = {"body": body, "created": created, "updated": stamp}
        _save(data)
    return {"title": title, "created": created, "updated": stamp}


@mcp.tool()
def update_note(title: str, body: str) -> dict:
    """Replace the body of an existing note, keeping its creation time.

    Args:
        title: the note to edit.
        body: the new note text.

    Returns:
        The title with its created/updated timestamps.

    Raises:
        NoteNotFound: no note has that title.
    """
    with _lock:
        data = _load()
        if title not in data:
            raise NoteNotFound(title)
        stamp = _now()
        data[title]["body"] = body
        data[title]["updated"] = stamp
        created = data[title].get("created", "")
        _save(data)
    return {"title": title, "created": created, "updated": stamp}


@mcp.tool()
def delete_note(title: str) -> dict:
    """Delete a note by title.

    Args:
        title: the note to remove.

    Returns:
        A dict naming the deleted note.

    Raises:
        NoteNotFound: no note has that title.
    """
    with _lock:
        data = _load()
        if title not in data:
            raise NoteNotFound(title)
        del data[title]
        _save(data)
    return {"deleted": title}


@mcp.tool()
def get_note(title: str) -> dict:
    """Fetch one note by its exact title.

    Args:
        title: the note to read.

    Returns:
        A dict with the title, body and created/updated timestamps.

    Raises:
        NoteNotFound: no note has that title. Raising keeps a real miss
            distinguishable from a note whose body happens to say so.
    """
    data = _load()
    if title not in data:
        raise NoteNotFound(title)
    rec = data[title]
    return {"title": title, "body": rec.get("body", ""),
            "created": rec.get("created", ""),
            "updated": rec.get("updated", "")}


@mcp.tool()
def list_notes(query: str = "", limit: int = 50, offset: int = 0) -> dict:
    """List stored notes, most recently updated first.

    Args:
        query: case-insensitive substring matched against title and body.
            Empty string lists everything.
        limit: maximum notes to return; capped at 500.
        offset: how many matches to skip, for paging.

    Returns:
        A dict with `total` matches and a `notes` list of
        {title, created, updated, preview} entries.
    """
    data = _load()
    needle = query.strip().lower()
    rows = []
    for title, rec in data.items():
        body = rec.get("body", "")
        if needle and needle not in title.lower() \
                and needle not in body.lower():
            continue
        rows.append({"title": title,
                     "created": rec.get("created", ""),
                     "updated": rec.get("updated", ""),
                     "preview": body[:120]})
    # Title breaks ties so the order never depends on dict insertion.
    rows.sort(key=lambda r: (r["updated"], r["title"]), reverse=True)
    start = max(0, offset)
    page = rows[start:start + max(1, min(500, limit))]
    return {"total": len(rows), "notes": page}

# keep this in sync with the docs

def main():
    global NOTES
    ap = argparse.ArgumentParser(
        prog="server",
        description="notes-box MCP server (stdio transport)")
    ap.add_argument(
        "--notes-file",
        help="where to keep the notes JSON "
             "(default: $MCP_NOTES_FILE, else ~/.mcp_notes.json)")
    args = ap.parse_args()
    if args.notes_file:
        NOTES = Path(args.notes_file)
    mcp.run()


if __name__ == "__main__":
    main()
