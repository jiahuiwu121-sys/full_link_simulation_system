#include "HBM34.h"

#include <DRAMPower/standards/hbm34/core_calculation_HBM34.h>

namespace DRAMPower
{

HBM34::HBM34(const MemSpecHBM34& spec) : m_spec(spec), m_core(m_spec)
{
}

void HBM34::doCoreCommandImpl(const Command& command)
{
    m_core.doCommand(command);
}

timestamp_t HBM34::getLastCommandTime_impl() const
{
    return m_core.getLastCommandTime();
}

bool HBM34::isSerializable() const
{
    return m_core.isSerializable();
}

SimulationStats HBM34::getWindowStats(timestamp_t timestamp)
{
    SimulationStats stats;
    m_core.getWindowStats(timestamp, stats);
    return stats;
}

util::CLIArchitectureConfig HBM34::getCLIArchitectureConfig()
{
    return {m_spec.numberOfDevices, m_spec.numberOfPseudoChannels, m_spec.numberOfBanks};
}

energy_t HBM34::calcCoreEnergyStats(const SimulationStats& stats) const
{
    return Calculation_HBM34(m_spec).calcEnergy(stats);
}

interface_energy_info_t HBM34::calcInterfaceEnergyStats(const SimulationStats& stats) const
{
    interface_energy_info_t energy;
    const double bitsPerCommand =
        static_cast<double>(m_spec.bitWidth * m_spec.burstLength * m_spec.numberOfDevices);
    double reads = 0.0;
    double writes = 0.0;
    for (const auto& bank : stats.bank)
    {
        reads += bank.counter.reads + bank.counter.readAuto;
        writes += bank.counter.writes + bank.counter.writeAuto;
    }
    energy.dram.dynamicEnergy = reads * bitsPerCommand * m_spec.interfacePower.readEnergyPerBit;
    energy.controller.dynamicEnergy =
        writes * bitsPerCommand * m_spec.interfacePower.writeEnergyPerBit;
    return energy;
}

} // namespace DRAMPower
