#pragma once
#include <array>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <map>
#include <stdexcept>

// The sole persistent byte store for the remote window. No request port bypass.
class TargetBackingStore {
    static constexpr uint64_t PageBytes = 4096;
    uint64_t size;
    std::map<uint64_t, std::array<uint8_t, PageBytes>> pages;
  public:
    explicit TargetBackingStore(uint64_t size_) : size(size_) {}
    uint64_t allocatedPages() const { return pages.size(); }
    void check(uint64_t addr, unsigned bytes) const {
        if (addr >= size || bytes > size - addr) throw std::out_of_range("target backing range");
    }
    void read(uint64_t addr, unsigned bytes, uint8_t* data) const {
        check(addr, bytes);
        for (unsigned j = 0; j < bytes; ++j) {
            auto p = pages.find((addr + j) / PageBytes);
            data[j] = p == pages.end() ? 0 : p->second[(addr + j) % PageBytes];
        }
    }
    void write(uint64_t addr, unsigned bytes, const uint8_t* data, const uint8_t* mask) {
        check(addr, bytes);
        for (unsigned j = 0; j < bytes; ++j) if (mask[j])
            pages[(addr + j) / PageBytes][(addr + j) % PageBytes] = data[j];
    }
    void dump(const std::string& path, uint64_t base) const {
        std::ofstream out(path); out << "address,data\n";
        for (const auto& page : pages) for (uint64_t offset = 0; offset < PageBytes; offset += 32) {
            if (page.first * PageBytes + offset >= size) break;
            out << std::dec << base + page.first * PageBytes + offset << ',';
            for (unsigned j = 0; j < 32 && page.first * PageBytes + offset + j < size; ++j)
                out << std::hex << std::setw(2) << std::setfill('0') << unsigned(page.second[offset + j]);
            out << '\n';
        }
        if (!out) throw std::runtime_error("cannot dump target backing");
    }
};
