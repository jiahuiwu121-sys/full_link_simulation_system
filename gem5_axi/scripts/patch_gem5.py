#!/usr/bin/env python3
"""Idempotent, guarded compatibility patch for the bundled gem5 revision.

TLM's data pointer is non-const even for writes. Packet::getPtr forbids masked
writes, while getConstPtr permits reading their raw source bytes. The AXI
conversion hook separately retains the mask; the AXI master never mutates
write data.
"""
from pathlib import Path
import sys

source = Path(sys.argv[1]) / "src/systemc/tlm_bridge/gem5_to_tlm.cc"

local_gem5 = Path(__file__).resolve().parents[2] / "gem5"
if Path(sys.argv[1]).resolve() == local_gem5.resolve():
    if ("packet->getConstPtr<unsigned char>()" not in source.read_text() or
            "str.resize(w);" not in (local_gem5 / "src/systemc/utils/vcd.cc").read_text()):
        raise RuntimeError("主仓库 gem5 缺少兼容适配；请直接审阅源码，不在构建时打补丁")
    print("主仓库 gem5 兼容适配已纳入源码，无需打补丁")
    raise SystemExit(0)
old = "    unsigned char *data = packet->getPtr<unsigned char>();"
new = """    // TLM requires a mutable pointer, but write data is input-only.
    // Permit masked writes; integration conversion hooks must preserve enables.
    unsigned char *data = packet->isWrite() ?
        const_cast<unsigned char *>(packet->getConstPtr<unsigned char>()) :
        packet->getPtr<unsigned char>();"""
text = source.read_text()
if new in text:
    print("gem5 masked-write compatibility patch already applied")
elif text.count(old) == 1:
    source.write_text(text.replace(old, new))
    print("Applied gem5 masked-write compatibility patch")
else:
    raise RuntimeError("Unexpected gem5 source; refusing an ambiguous patch")

# Native VCD integral traces indexed an empty std::string after reserve().
# This is undefined behaviour and emits unterminated / nonbinary bit strings.
source = Path(sys.argv[1]) / "src/systemc/utils/vcd.cc"
old = """        std::string str;
        str.reserve(w);

        const uint64_t val ="""
new = """        std::string str;
        // Indexed writes require a sized string, not only reserved capacity.
        str.resize(w);

        const uint64_t val ="""
text = source.read_text()
if new in text:
    print("gem5 integral VCD compatibility patch already applied")
elif text.count(old) == 1:
    source.write_text(text.replace(old, new))
    print("Applied gem5 integral VCD compatibility patch")
else:
    raise RuntimeError("Unexpected VCD source; refusing an ambiguous patch")
