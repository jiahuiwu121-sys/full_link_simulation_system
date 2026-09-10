#ifndef DRAMPOWER_STANDARDS_HBM34_CORE_CALCULATION_HBM34_H
#define DRAMPOWER_STANDARDS_HBM34_CORE_CALCULATION_HBM34_H

#include <DRAMPower/data/energy.h>
#include <DRAMPower/data/stats.h>
#include <DRAMPower/memspec/MemSpecHBM34.h>

namespace DRAMPower
{

class Calculation_HBM34
{
public:
    explicit Calculation_HBM34(const MemSpecHBM34& spec) : m_spec(spec) {}
    energy_t calcEnergy(const SimulationStats& stats) const;

private:
    const MemSpecHBM34& m_spec;
};

} // namespace DRAMPower

#endif
