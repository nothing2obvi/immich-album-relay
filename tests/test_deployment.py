import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("sync_test", "scripts/sync-test.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def test_sync_preserves_all_private_files_and_hashes(tmp_path):
    target = tmp_path / "private"
    target.mkdir()
    private = ["config.yml", ".env", "state/data", "logs/relay.log", "custom.private.yml"]
    for name in private:
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRIVATE-SECRET")
    root = Path.cwd()
    sync.synchronize(root, target)
    for name in private:
        assert (target / name).read_text() == "PRIVATE-SECRET"
    assert (target / "src/immich_album_relay/config.py").read_bytes() == (
        root / "src/immich_album_relay/config.py"
    ).read_bytes()
    assert not (target / ".git").exists()
    sync.synchronize(root, target)  # Repeatable without deleting private data.


def test_sync_rejects_nested_target(tmp_path):
    with pytest.raises(ValueError, match="separate"):
        sync.synchronize(tmp_path, tmp_path / "nested")


def test_sync_rejects_private_symlinks(tmp_path):
    target = tmp_path / "private"
    target.mkdir()
    outside = tmp_path / "protected"
    outside.write_text("DO-NOT-TOUCH")
    (target / "Dockerfile").symlink_to(outside)
    with pytest.raises(ValueError, match="Symlink"):
        sync.synchronize(Path.cwd(), target)
    assert outside.read_text() == "DO-NOT-TOUCH"


def test_sync_retires_only_previously_managed_application_files(tmp_path):
    import shutil

    source = tmp_path / "source"
    source.mkdir()
    for name in sync.FILES:
        shutil.copy2(Path.cwd() / name, source / name)
    (source / "src").mkdir()
    (source / "src/retired.py").write_text("old application")
    target = tmp_path / "private"
    sync.synchronize(source, target)
    (target / "src/private.txt").write_text("PRIVATE")
    (source / "src/retired.py").unlink()
    sync.synchronize(source, target)
    assert not (target / "src/retired.py").exists()
    assert (target / "src/private.txt").read_text() == "PRIVATE"


def test_manifest_cannot_delete_private_config(tmp_path):
    import json

    target = tmp_path / "private"
    target.mkdir()
    (target / "config.yml").write_text("PRIVATE")
    (target / sync.MANIFEST).write_text(json.dumps({"config.yml": "fake-hash"}))
    with pytest.raises(ValueError, match="invalid"):
        sync.synchronize(Path.cwd(), target)
    assert (target / "config.yml").read_text() == "PRIVATE"
