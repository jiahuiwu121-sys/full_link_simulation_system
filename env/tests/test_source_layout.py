"""Regression checks for ordinary source ownership and legacy cache restore."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ENV = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ENV / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class SourceLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.sources = module("check_sources")
        self.sources.ROOT = self.root
        for relative in self.sources.LOCAL_SOURCES["gem5"]:
            path = self.root / "gem5" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("source\n")
        subprocess.run(["git", "-C", str(self.root), "add", "gem5"], check=True)

    def test_ordinary_sources_are_accepted_without_upstream_git(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.sources.check_local("gem5")

    def test_leftover_gitlink_is_rejected(self):
        subprocess.run(["git", "-C", str(self.root), "rm", "--cached", "-r", "-q", "gem5"], check=True)
        subprocess.run(["git", "-C", str(self.root), "update-index", "--add", "--cacheinfo",
                        "160000," + "1" * 40 + ",gem5"], check=True)
        with self.assertRaisesRegex(ValueError, "子模块链接"):
            self.sources.check_local("gem5")

    def test_inner_git_pointer_is_rejected(self):
        (self.root / "gem5/.git").write_text("gitdir: missing\n")
        with self.assertRaisesRegex(ValueError, "内部 .git"):
            self.sources.check_local("gem5")

    def test_double_nested_source_is_rejected(self):
        entry = self.root / "gem5/SConstruct"
        nested = self.root / "gem5/gem5"
        nested.mkdir()
        entry.rename(nested / entry.name)
        with self.assertRaisesRegex(ValueError, "多嵌套"):
            self.sources.check_local("gem5")


class LegacyBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.root = base / "workspace"
        self.bundle = base / "bundle"
        self.bundle.mkdir()
        (self.root / "env").mkdir(parents=True)
        self.tool = module("dependency_bundle")
        self.tool.ROOT = self.root
        self.current = {"vortex-gpu/vortex": "vortex-pin"}
        self.old = dict(self.current, gem5="gem5-pin", coralnpu="npu-pin")
        self.vendors = {name: {"declared_upstream_revision": revision}
                        for name, revision in self.old.items() if name != "vortex-gpu/vortex"}
        (self.root / "env/sources.lock.json").write_text(json.dumps(self.current))
        (self.root / "env/vendored_sources.json").write_text(json.dumps(self.vendors))
        for name in self.vendors:
            (self.root / name).mkdir()
            (self.root / name / "preserve.cc").write_text("project-owned\n")
        locks = self.bundle / "locks"
        locks.mkdir()
        (locks / "sources.lock.json").write_text(json.dumps(self.old))
        (self.bundle / "cache").mkdir()
        (self.bundle / "cache/tool-package").write_text("cached tool\n")
        self.write_manifest()

    def write_manifest(self):
        manifest = {
            "format": 1,
            "locks": {"sources.lock.json": self.tool.digest(self.bundle / "locks/sources.lock.json")},
            "submodules": [{"path": name, "revision": revision} for name, revision in self.old.items()
                           if name != "vortex-gpu/vortex"],
            "files": {str(path.relative_to(self.bundle)): {
                "sha256": self.tool.digest(path), "bytes": path.stat().st_size}
                for path in self.bundle.rglob("*") if path.is_file() and path.name != "manifest.json"},
        }
        (self.bundle / "manifest.json").write_text(json.dumps(manifest))

    def test_old_cache_restore_preserves_project_sources(self):
        before = {name: hashlib.sha256((self.root / name / "preserve.cc").read_bytes()).hexdigest()
                  for name in self.vendors}
        destination = self.root.parent / "deps"
        with contextlib.redirect_stdout(io.StringIO()):
            self.tool.install(self.bundle, destination)
        self.assertEqual((destination / "tool-package").read_text(), "cached tool\n")
        for name, digest in before.items():
            self.assertEqual(hashlib.sha256((self.root / name / "preserve.cc").read_bytes()).hexdigest(), digest)
            self.assertFalse((self.root / name / ".git").exists())

    def test_changed_external_revision_is_rejected(self):
        self.old["vortex-gpu/vortex"] = "different-pin"
        (self.bundle / "locks/sources.lock.json").write_text(json.dumps(self.old))
        self.write_manifest()
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            self.tool.verify(self.bundle)

    def test_damaged_cache_is_rejected(self):
        (self.bundle / "cache/tool-package").write_text("damaged\n")
        with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
            self.tool.verify(self.bundle)


if __name__ == "__main__":
    unittest.main()
