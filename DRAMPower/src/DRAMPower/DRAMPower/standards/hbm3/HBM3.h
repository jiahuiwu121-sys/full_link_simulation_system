#ifndef DRAMPOWER_STANDARDS_HBM3_HBM3_H
#define DRAMPOWER_STANDARDS_HBM3_HBM3_H

#include <DRAMPower/memspec/MemSpecHBM3.h>
#include <DRAMPower/standards/hbm34/HBM34.h>

namespace DRAMPower
{

class HBM3 final : public HBM34
{
public:
    explicit HBM3(const MemSpecHBM3& spec) : HBM34(spec) {}
};

} // namespace DRAMPower

#endif
