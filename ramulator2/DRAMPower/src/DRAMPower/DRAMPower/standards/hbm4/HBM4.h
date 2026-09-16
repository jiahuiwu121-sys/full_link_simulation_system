#ifndef DRAMPOWER_STANDARDS_HBM4_HBM4_H
#define DRAMPOWER_STANDARDS_HBM4_HBM4_H

#include <DRAMPower/memspec/MemSpecHBM4.h>
#include <DRAMPower/standards/hbm34/HBM34.h>

namespace DRAMPower
{

class HBM4 final : public HBM34
{
public:
    explicit HBM4(const MemSpecHBM4& spec) : HBM34(spec) {}
};

} // namespace DRAMPower

#endif
