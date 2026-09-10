#ifndef DRAMPOWER_STANDARDS_HBM34_HBM34CORE_H
#define DRAMPOWER_STANDARDS_HBM34_HBM34CORE_H

#include <DRAMPower/Types.h>
#include <DRAMPower/command/Command.h>
#include <DRAMPower/data/stats.h>
#include <DRAMPower/dram/PseudoChannel.h>
#include <DRAMPower/memspec/MemSpecHBM34.h>
#include <DRAMPower/util/ImplicitCommandHandler.h>

#include <cstddef>
#include <cstdint>
#include <vector>

namespace DRAMPower
{

struct HBM34CoreMemSpec
{
    explicit HBM34CoreMemSpec(const MemSpecHBM34& spec) :
        pseudoChannels(spec.numberOfPseudoChannels),
        banksPerPseudoChannel(spec.numberOfBanks),
        sids(spec.numberOfSIDs),
        bankGroups(spec.numberOfBankGroups),
        banksPerGroup(spec.numberOfBanksPerGroup),
        tRAS(spec.memTimingSpec.tRAS),
        tRCDRD(spec.memTimingSpec.tRCDRD),
        tRCDWR(spec.memTimingSpec.tRCDWR),
        tRP(spec.memTimingSpec.tRP),
        tRFC(spec.memTimingSpec.tRFC),
        tRFCPB(spec.memTimingSpec.tRFCPB),
        tRFMAB(spec.memTimingSpec.tRFMAB),
        tRFMPB(spec.memTimingSpec.tRFMPB),
        prechargeOffsetRD(spec.prechargeOffsetRD),
        prechargeOffsetWR(spec.prechargeOffsetWR)
    {
    }

    std::size_t pseudoChannels;
    std::size_t banksPerPseudoChannel;
    std::size_t sids;
    std::size_t bankGroups;
    std::size_t banksPerGroup;
    timestamp_t tRAS;
    timestamp_t tRCDRD;
    timestamp_t tRCDWR;
    timestamp_t tRP;
    timestamp_t tRFC;
    timestamp_t tRFCPB;
    timestamp_t tRFMAB;
    timestamp_t tRFMPB;
    timestamp_t prechargeOffsetRD;
    timestamp_t prechargeOffsetWR;
};

class HBM34Core
{
public:
    explicit HBM34Core(const MemSpecHBM34& spec);

    void doCommand(const Command& command);
    timestamp_t getLastCommandTime() const;
    bool isSerializable() const;
    void getWindowStats(timestamp_t timestamp, SimulationStats& stats);

private:
    std::size_t pseudoChannelIndex(const Command& command) const;
    std::size_t bankIndex(const Command& command) const;

    void handleAct(PseudoChannel& pseudoChannel, Bank& bank, timestamp_t timestamp);
    void handlePre(PseudoChannel& pseudoChannel, Bank& bank, timestamp_t timestamp);
    void handlePreImpl(PseudoChannel& pseudoChannel, Bank& bank, timestamp_t timestamp);
    void handlePreAll(std::size_t pc, timestamp_t timestamp);
    void handleRead(std::size_t pc, std::size_t bank, timestamp_t timestamp, bool autoPrecharge);
    void handleWrite(std::size_t pc, std::size_t bank, timestamp_t timestamp, bool autoPrecharge);
    void
    handleAllBankOperation(std::size_t pc, timestamp_t timestamp, timestamp_t duration, bool rfm);
    void handlePerBankOperation(
        std::size_t pc, std::size_t bank, timestamp_t timestamp, timestamp_t duration, bool rfm);
    void scheduleOperationEnd(std::size_t pc,
                              std::size_t bank,
                              timestamp_t timestamp,
                              timestamp_t duration);

    HBM34CoreMemSpec m_spec;
    std::vector<PseudoChannel> m_pseudoChannels;
    ImplicitCommandHandler<HBM34Core> m_implicitCommands;
    timestamp_t m_lastCommandTime = 0;
};

} // namespace DRAMPower

#endif
