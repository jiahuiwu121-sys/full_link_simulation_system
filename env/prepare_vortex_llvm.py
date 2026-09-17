#!/usr/bin/env python3
"""Give the fixed LLVM binaries their private glibc loader, without global preload."""
import os
from pathlib import Path
import subprocess
root=Path(os.environ['SS_DEPS_ROOT'])
llvm=root/'xpu-toolchains/llvm-vortex'
libc=root/'xpu-sysroot/x86_64-conda-linux-gnu/sysroot/lib64'
patch=root/'xpu-sysroot/bin/patchelf'
env=dict(os.environ);env.pop('LD_LIBRARY_PATH',None)
# On modern hosts use the host loader and libc together. Mixing a private
# glibc 2.34 with host libm/libgcc from Ubuntu 24.04 is not a valid runtime.
host_version = tuple(map(int, os.confstr('CS_GNU_LIBC_VERSION').split()[-1].split('.')))
loader = Path('/lib64/ld-linux-x86-64.so.2') if host_version >= (2,34) else libc/'ld-linux-x86-64.so.2'
rpath = '$ORIGIN/../lib:' + os.environ['SS_PREFIX']+'/lib'
if host_version < (2,34): rpath = '$ORIGIN/../lib:'+str(libc)+':'+os.environ['SS_PREFIX']+'/lib'
seen=set()
for path in (llvm/'bin').iterdir():
    p=path.resolve()
    if not p.is_file() or p in seen:continue
    seen.add(p)
    with p.open('rb') as f:
        if f.read(4)!=b'\x7fELF':continue
    probe=subprocess.run([str(patch),'--print-interpreter',str(p)],env=env,capture_output=True)
    if probe.returncode:continue
    subprocess.run([str(patch),'--set-interpreter',str(loader),
                    '--force-rpath','--set-rpath',rpath,str(p)],check=True,env=env)
print('Prepared LLVM runtime:',loader)
