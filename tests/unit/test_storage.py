"""Storage directory resolution, including the fallback when the configured dir is not writable."""

from app.config import get_settings
from app.services import storage


def test_uses_configured_dir_when_writable(monkeypatch, tmp_path):
    d = tmp_path / "storage"
    monkeypatch.setattr(get_settings(), "storage_dir", str(d))
    assert storage.root() == d.resolve()


def test_falls_back_to_temp_when_dir_unwritable(monkeypatch, tmp_path):
    # A file where a directory is expected: mkdir under it raises OSError, triggering the fallback.
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.setattr(get_settings(), "storage_dir", str(blocker / "sub" / "storage"))
    fake_tmp = tmp_path / "tmp"
    fake_tmp.mkdir()
    monkeypatch.setattr(storage.tempfile, "gettempdir", lambda: str(fake_tmp))

    root = storage.root()

    assert root == (fake_tmp / "career-agent-storage").resolve()
    # And a document can be stored and read back without error.
    uri = storage.save_document(b"hello", "a" * 64, ".pdf")
    assert (root / uri).read_bytes() == b"hello"
