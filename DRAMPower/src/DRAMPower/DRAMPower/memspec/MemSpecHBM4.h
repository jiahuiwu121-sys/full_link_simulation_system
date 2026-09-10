#ifndef DRAMPOWER_MEMSPEC_MEMSPECHBM4_H
#define DRAMPOWER_MEMSPEC_MEMSPECHBM4_H

#include "MemSpecHBM34.h"

namespace DRAMPower
{

class MemSpecHBM4 final : public MemSpecHBM34
{
public:
    explicit MemSpecHBM4(const json_t& data) : MemSpecHBM34(data, "HBM4") {}
};

} // namespace DRAMPower

#endif /* DRAMPOWER_MEMSPEC_MEMSPECHBM4_H */
