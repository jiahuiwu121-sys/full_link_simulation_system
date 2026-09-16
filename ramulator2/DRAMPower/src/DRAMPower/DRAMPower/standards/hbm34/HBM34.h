#ifndef DRAMPOWER_STANDARDS_HBM34_HBM34_H
#define DRAMPOWER_STANDARDS_HBM34_HBM34_H

#include <DRAMPower/dram/dram_base.h>
#include <DRAMPower/memspec/MemSpecHBM34.h>
#include <DRAMPower/standards/hbm34/HBM34Core.h>

namespace DRAMPower
{

class HBM34 : public dram_base<CmdType>
{
public:
    explicit HBM34(const MemSpecHBM34& spec);
    ~HBM34() override = default;

    energy_t calcCoreEnergyStats(const SimulationStats& stats) const override;
    interface_energy_info_t calcInterfaceEnergyStats(const SimulationStats& stats) const override;
    SimulationStats getWindowStats(timestamp_t timestamp) override;
    util::CLIArchitectureConfig getCLIArchitectureConfig() override;
    bool isSerializable() const override;

    const MemSpecHBM34& getMemSpec() const { return m_spec; }
    HBM34Core& getCore() { return m_core; }
    const HBM34Core& getCore() const { return m_core; }

private:
    void doCoreCommandImpl(const Command& command) override;
    void doInterfaceCommandImpl(const Command&) override {}
    timestamp_t getLastCommandTime_impl() const override;

    MemSpecHBM34 m_spec;
    HBM34Core m_core;
};

} // namespace DRAMPower

#endif
