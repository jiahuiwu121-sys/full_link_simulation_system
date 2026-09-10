#include <gtest/gtest.h>

#include <DRAMPower/command/Command.h>
#include <DRAMPower/memspec/MemSpecHBM3.h>
#include <DRAMPower/memspec/MemSpecHBM4.h>
#include <DRAMPower/standards/hbm3/HBM3.h>
#include <DRAMPower/standards/hbm4/HBM4.h>

#include <DRAMUtils/util/json.h>

#include <cmath>
#include <fstream>
#include <string>

namespace
{

json_t loadProfile(const char* filename)
{
    std::ifstream input(std::string(HBM34_EXAMPLE_DIR) + filename);
    if (!input)
        throw std::runtime_error("Unable to load HBM3/HBM4 test profile");
    return json_t::parse(input);
}

DRAMPower::TargetCoordinate
target(std::size_t pc, std::size_t sid, std::size_t bg, std::size_t bank)
{
    return {bank, bg, 0, 0, 0, pc, sid, 0};
}

} // namespace

TEST(HBM34Model, HBM3UsesHalfCycleTimeAndFullHierarchy)
{
    using namespace DRAMPower;
    MemSpecHBM3 spec(loadProfile("hbm3_6400_estimated.json"));
    EXPECT_DOUBLE_EQ(spec.memTimingSpec.tCK, 625e-12);
    EXPECT_DOUBLE_EQ(spec.memTimingSpec.timeUnit, 312.5e-12);
    EXPECT_EQ(spec.numberOfBanks, 32);

    HBM3 model(spec);
    model.doCommand({0, CmdType::ACT, target(1, 1, 1, 3)});
    model.doCommand({100, CmdType::RD, target(1, 1, 1, 3)});
    model.doCommand({160, CmdType::PRE, target(1, 1, 1, 3)});
    model.doCommand({300, CmdType::REFA, target(0, 0, 0, 0)});
    model.doCommand({300, CmdType::RFMPB, target(1, 1, 1, 3)});

    const auto stats = model.getWindowStats(2000);
    const std::size_t flattenedBank = (1 * 4 + 1) * 4 + 3;
    const std::size_t statsIndex = spec.numberOfBanks + flattenedBank;
    EXPECT_EQ(stats.bank[statsIndex].counter.act, 1);
    EXPECT_EQ(stats.bank[statsIndex].counter.reads, 1);
    EXPECT_EQ(stats.bank[statsIndex].counter.rfmPerBank, 1);
    for (std::size_t bank = 0; bank < spec.numberOfBanks; ++bank)
    {
        EXPECT_EQ(stats.bank[bank].counter.refAllBank, 1);
    }

    const auto energy = model.calcCoreEnergyStats(stats);
    EXPECT_GT(energy.total(), 0.0);
    EXPECT_GT(energy.bank_energy[statsIndex].E_RD, 0.0);
    EXPECT_GT(energy.bank_energy[statsIndex].E_RFM_PB, 0.0);
}

TEST(HBM34Model, HBM4ProfileCarriesExplicitExtrapolationMetadata)
{
    using namespace DRAMPower;
    MemSpecHBM4 spec(loadProfile("hbm4_8000_estimated.json"));
    EXPECT_EQ(spec.memoryType, "HBM4");
    EXPECT_EQ(spec.metadata.modelKind, "extrapolated");
    EXPECT_FALSE(spec.metadata.absoluteAccuracyValidated);
    EXPECT_NEAR(spec.memPowerSpec[MemSpecHBM34::VDD].i4R, 0.77935, 1e-12);
    EXPECT_DOUBLE_EQ(spec.memTimingSpec.timeUnit, 250e-12);

    HBM4 model(spec);
    model.doCommand({0, CmdType::ACT, target(0, 0, 0, 0)});
    model.doCommand({100, CmdType::WR, target(0, 0, 0, 0)});
    model.doCommand({200, CmdType::PRE, target(0, 0, 0, 0)});
    model.doCommand({500, CmdType::RFMAB, target(0, 0, 0, 0)});
    const auto energy = model.calcCoreEnergy(2500);
    EXPECT_TRUE(std::isfinite(energy.total()));
    EXPECT_GT(energy.total(), 0.0);
    EXPECT_GT(energy.bank_energy[0].E_WR, 0.0);
    EXPECT_GT(energy.bank_energy[0].E_RFM_AB, 0.0);
}
