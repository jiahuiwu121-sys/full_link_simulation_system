#ifndef DRAMPOWER_FACTORY_MEMORYFACTORY_H
#define DRAMPOWER_FACTORY_MEMORYFACTORY_H

#include <filesystem>
#include <memory>

#include <DRAMPower/command/CmdType.h>
#include <DRAMPower/dram/dram_base.h>
#include <DRAMPower/simconfig/simconfig.h>

namespace DRAMPower
{

// Construct a supported power model from a memspec file without depending on
// the command-line library. Supported types are HBM3, HBM4, LPDDR5 and LPDDR6.
std::unique_ptr<dram_base<CmdType>> createMemoryModel(const std::filesystem::path& memspecPath,
                                                      const config::SimConfig& simConfig = {});

} // namespace DRAMPower

#endif // DRAMPOWER_FACTORY_MEMORYFACTORY_H
