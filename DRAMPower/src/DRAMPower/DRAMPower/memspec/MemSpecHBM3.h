#ifndef DRAMPOWER_MEMSPEC_MEMSPECHBM3_H
#define DRAMPOWER_MEMSPEC_MEMSPECHBM3_H

#include "MemSpecHBM34.h"

namespace DRAMPower
{

class MemSpecHBM3 final : public MemSpecHBM34
{
public:
    explicit MemSpecHBM3(const json_t& data) : MemSpecHBM34(data, "HBM3") {}
};

} // namespace DRAMPower

#endif /* DRAMPOWER_MEMSPEC_MEMSPECHBM3_H */
