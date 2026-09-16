#include <DRAMPower/factory/MemoryFactory.h>

#include <fstream>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <variant>

#include <DRAMPower/memspec/MemSpecHBM3.h>
#include <DRAMPower/memspec/MemSpecHBM4.h>
#include <DRAMPower/memspec/MemSpecLPDDR5.h>
#include <DRAMPower/memspec/MemSpecLPDDR6.h>
#include <DRAMPower/standards/hbm3/HBM3.h>
#include <DRAMPower/standards/hbm4/HBM4.h>
#include <DRAMPower/standards/lpddr5/LPDDR5.h>
#include <DRAMPower/standards/lpddr6/LPDDR6.h>
#include <DRAMUtils/memspec/MemSpec.h>
#include <DRAMUtils/memspec/standards/MemSpecLPDDR5.h>
#include <DRAMUtils/memspec/standards/MemSpecLPDDR6.h>
#include <DRAMUtils/util/json.h>

namespace DRAMPower
{

std::unique_ptr<dram_base<CmdType>> createMemoryModel(const std::filesystem::path& memspecPath,
                                                      const config::SimConfig& simConfig)
{
    std::ifstream input(memspecPath);
    if (!input.is_open())
    {
        throw std::runtime_error("Cannot open DRAMPower memspec: " + memspecPath.string());
    }

    json_t root = json_t::parse(input);
    const auto& body = root.contains("memspec") ? root.at("memspec") : root;
    const std::string memoryType = body.value("memoryType", std::string{});

    if (memoryType == "HBM3")
    {
        return std::make_unique<HBM3>(MemSpecHBM3(body));
    }
    if (memoryType == "HBM4")
    {
        return std::make_unique<HBM4>(MemSpecHBM4(body));
    }

    auto memspec = DRAMUtils::parse_memspec_from_file(memspecPath);
    if (!memspec)
    {
        throw std::runtime_error("DRAMUtils could not parse memspec: " + memspecPath.string());
    }

    std::unique_ptr<dram_base<CmdType>> result;
    std::visit(
        [&result, &simConfig](auto&& spec)
        {
            using T = std::decay_t<decltype(spec)>;
            if constexpr (std::is_same_v<T, DRAMUtils::MemSpec::MemSpecLPDDR5>)
            {
                result = std::make_unique<LPDDR5>(MemSpecLPDDR5(spec), simConfig);
            }
            else if constexpr (std::is_same_v<T, DRAMUtils::MemSpec::MemSpecLPDDR6>)
            {
                result = std::make_unique<LPDDR6>(MemSpecLPDDR6(spec), simConfig);
            }
        },
        memspec->getVariant());

    if (!result)
    {
        throw std::runtime_error("Unsupported DRAMPower memoryType '" + memoryType +
                                 "'; expected HBM3, HBM4, LPDDR5 or LPDDR6");
    }
    return result;
}

} // namespace DRAMPower
