#!/usr/bin/env python3
"""Record the actual source files, compiler, packages and linked runtime."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
prefix = Path(os.environ["SS_PREFIX"])
destination = Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


packages = [json.loads(p.read_text()) for p in sorted((prefix / "conda-meta").glob("*.json"))]
actual = {p["url"] + "#" + p["md5"] for p in packages}
expected = {line for line in (root / "env/conda-linux-64.lock").read_text().splitlines()
            if line.startswith("https://")}
if actual != expected:
    raise SystemExit("Toolchain differs from env/conda-linux-64.lock; use a fresh SS_DEPS_ROOT")

binary = Path(os.environ["AXI_GEM5_BIN"])
linked = command("ldd", str(binary))
if "not found" in linked or "libsystemc" in linked.lower():
    raise SystemExit("Unexpected/missing runtime library:\n" + linked)
sources = {}
backend = os.environ.get('SS_MEMORY_BACKEND', 'ramulator2')
source_names = ["gem5", "gem5_new", "gem5_axi", "axi2flit", "ucie-model", "protocol", "ramulator2"]
if backend == 'memsim': source_names.append('mem_sim')
if os.environ.get('SS_RUN_XPU') == '1': source_names += ['coralnpu','vortex-gpu/vortex']
for name in source_names:
    repo = root / name
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
                          capture_output=True, text=True)
    files = command("git", "-C", str(repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", ".").split("\0")
    sources[name] = {
        "revision": head.stdout.strip() if head.returncode == 0 else None,
        "kind": "monorepo" if Path(command("git", "-C", str(repo), "rev-parse", "--show-toplevel")) == root else "submodule",
        "status": command("git", "-C", str(repo), "status", "--short", "--", "."),
        "files_sha256": {f: sha(repo / f) for f in sorted(set(files)) if (repo / f).is_file()},
    }
    (destination / (name.replace('/', '-') + ".patch")).write_text(command("git", "-C", str(repo), "diff", "--relative", "--binary", "--", ".") + "\n")
manifest = {
    "platform": platform.platform(), "machine": platform.machine(),
    "workspace": str(root), "workspace_revision": command("git", "-C", str(root), "rev-parse", "HEAD"),
    "internal_imports": json.loads((root / "env/internal_imports.json").read_text()), "toolchain_prefix": str(prefix),
    "vendored_sources": json.loads((root / "env/vendored_sources.json").read_text()),
    "python": sys.version, "compiler": command(os.environ["AXI_CXX"], "--version"),
    "scons": command(str(prefix / "bin/scons"), "--version"),
    "packages": [{k: p[k] for k in ("name", "version", "build", "url", "md5")} for p in packages],
    "memory_backend": backend,
    "ramulator_library_sha256": sha(root / 'build/ramulator2/lib/libstoragestacked_ramulator2.so'),
    "binary": str(binary), "binary_sha256": sha(binary), "ldd": linked,
    "gem5_build_config": (root / "gem5/build/AXI/gem5.build/config").read_text(),
    "systemc": "gem5 native; no external libsystemc", "ticks_per_second": 10**15,
    "sources": sources,
    "environment_files_sha256": {p.name: sha(p) for p in sorted((root / "env").iterdir()) if p.is_file()},
}
native_library = root / 'build/ramulator2/lib/libstoragestacked_ramulator2.so'
native_linked = command('ldd', str(native_library))
if 'not found' in native_linked or 'libsystemc' in native_linked.lower():
    raise SystemExit('Unexpected native Ramulator runtime: ' + native_linked)
symbols = command('nm','-a','-C',str(native_library))
if any(token in symbols for token in ('sc_core::','sc_dt::','sc_main')):
    raise SystemExit('Ramulator library contains a second SystemC implementation')
exports = [line.split()[-1] for line in command('nm','-D','--defined-only',str(native_library)).splitlines()]
if not exports or any(not name.startswith('ssr_') for name in exports):
    raise SystemExit('Online Ramulator library exposes conflicting C++ symbols: '+str(exports[:20]))
manifest['ramulator_runtime'] = {'ldd':native_linked,'embedded_systemc_symbols':0,'exports':exports}
manifest['ramulator_build_cache'] = (root/'build/ramulator2/CMakeCache.txt').read_text()
if backend == 'memsim':
    manifest['memsim_library_sha256'] = sha(Path(os.environ['MEMSIM_BUILD'])/'libstoragestacked_memsim.so')
(destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Recorded:", destination / "manifest.json")
