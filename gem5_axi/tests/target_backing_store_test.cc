#include "target_backing_store.hh"
#include <array>
#include <stdexcept>
#include <iostream>

static void require(bool ok) {
    if (!ok) throw std::runtime_error("backing contract failed");
}
int main() {
    try {
        TargetBackingStore store(0x170000000ULL);
        std::array<uint8_t, 32> data{}, mask{}, out{};
        store.read(0x100000000ULL, 32, out.data());
        require(out == data && store.allocatedPages() == 0);
        for (unsigned i = 0; i < 32; ++i) { data[i] = 17 + i; mask[i] = i % 2; }
        store.write(4090, 32, data.data(), mask.data());
        store.read(4090, 32, out.data());
        for (unsigned i = 0; i < 32; ++i) require(out[i] == (mask[i] ? data[i] : 0));
        require(store.allocatedPages() == 2);
        mask.fill(1); store.write(0x100000000ULL + 4090, 32, data.data(), mask.data());
        store.read(0x100000000ULL + 4090, 32, out.data()); require(out == data);
        store.read(4090, 32, out.data());
        for (unsigned i = 0; i < 32; ++i) require(out[i] == (i % 2 ? data[i] : 0));
        require(store.allocatedPages() == 4);
        bool rejected = false;
        try { store.write(0x16ffffff0ULL, 32, data.data(), mask.data()); }
        catch (const std::out_of_range&) { rejected = true; }
        require(rejected && store.allocatedPages() == 4);
        rejected = false;
        try { store.read(UINT64_MAX - 1, 32, out.data()); }
        catch (const std::out_of_range&) { rejected = true; }
        require(rejected);
        std::cout << "sparse zero/mask/page crossing/64bit alias/range contracts passed\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
