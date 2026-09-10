#include "HBM34Core.h"

#include <algorithm>
#include <stdexcept>

namespace DRAMPower
{

HBM34Core::HBM34Core(const MemSpecHBM34& spec) :
    m_spec(spec),
    m_pseudoChannels(spec.numberOfPseudoChannels, PseudoChannel(spec.numberOfBanks))
{
}

std::size_t HBM34Core::pseudoChannelIndex(const Command& command) const
{
    const auto pc = command.targetCoordinate.pseudoChannel;
    if (pc >= m_spec.pseudoChannels)
    {
        throw std::out_of_range("HBM3/HBM4 pseudo-channel coordinate out of range");
    }
    return pc;
}

std::size_t HBM34Core::bankIndex(const Command& command) const
{
    const auto& target = command.targetCoordinate;
    if (target.sid >= m_spec.sids || target.bankGroup >= m_spec.bankGroups ||
        target.bank >= m_spec.banksPerGroup)
    {
        throw std::out_of_range("HBM3/HBM4 SID/bank-group/bank coordinate out of range");
    }
    return (target.sid * m_spec.bankGroups + target.bankGroup) * m_spec.banksPerGroup + target.bank;
}

void HBM34Core::doCommand(const Command& command)
{
    m_implicitCommands.processImplicitCommandQueue(*this, command.timestamp, m_lastCommandTime);
    m_lastCommandTime = std::max(m_lastCommandTime, command.timestamp);

    if (command.type == CmdType::END_OF_SIMULATION || command.type == CmdType::NOP)
        return;

    if (command.targetCoordinate.channel != 0)
    {
        throw std::out_of_range(
            "One HBM3/HBM4 DRAMPower instance accepts commands for channel 0 only");
    }

    const auto pc = pseudoChannelIndex(command);
    auto& pseudoChannel = m_pseudoChannels[pc];
    switch (command.type)
    {
    case CmdType::ACT:
        handleAct(pseudoChannel, pseudoChannel.banks[bankIndex(command)], command.timestamp);
        break;
    case CmdType::PRE:
        handlePre(pseudoChannel, pseudoChannel.banks[bankIndex(command)], command.timestamp);
        break;
    case CmdType::PREA:
        handlePreAll(pc, command.timestamp);
        break;
    case CmdType::RD:
        handleRead(pc, bankIndex(command), command.timestamp, false);
        break;
    case CmdType::RDA:
        handleRead(pc, bankIndex(command), command.timestamp, true);
        break;
    case CmdType::WR:
        handleWrite(pc, bankIndex(command), command.timestamp, false);
        break;
    case CmdType::WRA:
        handleWrite(pc, bankIndex(command), command.timestamp, true);
        break;
    case CmdType::REFB:
        handlePerBankOperation(pc, bankIndex(command), command.timestamp, m_spec.tRFCPB, false);
        break;
    case CmdType::REFA:
        handleAllBankOperation(pc, command.timestamp, m_spec.tRFC, false);
        break;
    case CmdType::RFMPB:
        handlePerBankOperation(pc, bankIndex(command), command.timestamp, m_spec.tRFMPB, true);
        break;
    case CmdType::RFMAB:
        handleAllBankOperation(pc, command.timestamp, m_spec.tRFMAB, true);
        break;
    default:
        throw std::invalid_argument("Command is not supported by the HBM3/HBM4 model");
    }
}

void HBM34Core::handleAct(PseudoChannel& pseudoChannel, Bank& bank, timestamp_t timestamp)
{
    if (bank.bankState == Bank::BankState::BANK_ACTIVE)
        return;
    bank.bankState = Bank::BankState::BANK_ACTIVE;
    ++bank.counter.act;
    bank.cycles.act.start_interval(timestamp);
    pseudoChannel.cycles.act.start_interval_if_not_running(timestamp);
}

void HBM34Core::handlePreImpl(PseudoChannel& pseudoChannel, Bank& bank, timestamp_t timestamp)
{
    if (bank.bankState == Bank::BankState::BANK_PRECHARGED)
        return;
    bank.bankState = Bank::BankState::BANK_PRECHARGED;
    bank.latestPre = timestamp;
    bank.cycles.act.close_interval(timestamp);
    if (!pseudoChannel.isActive())
        pseudoChannel.cycles.act.close_interval(timestamp);
}

void HBM34Core::handlePre(PseudoChannel& pseudoChannel, Bank& bank, timestamp_t timestamp)
{
    ++bank.counter.pre;
    handlePreImpl(pseudoChannel, bank, timestamp);
}

void HBM34Core::handlePreAll(std::size_t pc, timestamp_t timestamp)
{
    auto& pseudoChannel = m_pseudoChannels[pc];
    for (auto& bank : pseudoChannel.banks)
        handlePre(pseudoChannel, bank, timestamp);
}

void HBM34Core::handleRead(std::size_t pc,
                           std::size_t bankIndex,
                           timestamp_t timestamp,
                           bool autoPrecharge)
{
    auto& pseudoChannel = m_pseudoChannels[pc];
    auto& bank = pseudoChannel.banks[bankIndex];
    if (!autoPrecharge)
    {
        ++bank.counter.reads;
        return;
    }
    ++bank.counter.readAuto;
    const auto completion =
        std::max(bank.cycles.act.get_start() + m_spec.tRAS, timestamp + m_spec.prechargeOffsetRD);
    bank.latestAutoPreFinished = completion;
    m_implicitCommands.addImplicitCommand(
        completion,
        [pc, bankIndex, completion](HBM34Core& self)
        {
            self.handlePre(
                self.m_pseudoChannels[pc], self.m_pseudoChannels[pc].banks[bankIndex], completion);
        });
}

void HBM34Core::handleWrite(std::size_t pc,
                            std::size_t bankIndex,
                            timestamp_t timestamp,
                            bool autoPrecharge)
{
    auto& pseudoChannel = m_pseudoChannels[pc];
    auto& bank = pseudoChannel.banks[bankIndex];
    if (!autoPrecharge)
    {
        ++bank.counter.writes;
        return;
    }
    ++bank.counter.writeAuto;
    const auto completion =
        std::max(bank.cycles.act.get_start() + m_spec.tRAS, timestamp + m_spec.prechargeOffsetWR);
    bank.latestAutoPreFinished = completion;
    m_implicitCommands.addImplicitCommand(
        completion,
        [pc, bankIndex, completion](HBM34Core& self)
        {
            self.handlePre(
                self.m_pseudoChannels[pc], self.m_pseudoChannels[pc].banks[bankIndex], completion);
        });
}

void HBM34Core::scheduleOperationEnd(std::size_t pc,
                                     std::size_t bankIndex,
                                     timestamp_t timestamp,
                                     timestamp_t duration)
{
    auto& pseudoChannel = m_pseudoChannels[pc];
    auto& bank = pseudoChannel.banks[bankIndex];
    pseudoChannel.cycles.act.start_interval_if_not_running(timestamp);
    bank.cycles.act.start_interval_if_not_running(timestamp);
    const auto completion = timestamp + duration;
    bank.refreshEndTime = completion;
    m_implicitCommands.addImplicitCommand(
        completion,
        [pc, bankIndex, completion](HBM34Core& self)
        {
            self.handlePreImpl(
                self.m_pseudoChannels[pc], self.m_pseudoChannels[pc].banks[bankIndex], completion);
        });
}

void HBM34Core::handleAllBankOperation(std::size_t pc,
                                       timestamp_t timestamp,
                                       timestamp_t duration,
                                       bool rfm)
{
    auto& pseudoChannel = m_pseudoChannels[pc];
    pseudoChannel.endRefreshTime = timestamp + duration;
    for (std::size_t bank = 0; bank < pseudoChannel.banks.size(); ++bank)
    {
        if (rfm)
            ++pseudoChannel.banks[bank].counter.rfmAllBank;
        else
            ++pseudoChannel.banks[bank].counter.refAllBank;
        scheduleOperationEnd(pc, bank, timestamp, duration);
    }
}

void HBM34Core::handlePerBankOperation(
    std::size_t pc, std::size_t bank, timestamp_t timestamp, timestamp_t duration, bool rfm)
{
    if (rfm)
        ++m_pseudoChannels[pc].banks[bank].counter.rfmPerBank;
    else
        ++m_pseudoChannels[pc].banks[bank].counter.refPerBank;
    scheduleOperationEnd(pc, bank, timestamp, duration);
}

timestamp_t HBM34Core::getLastCommandTime() const
{
    return m_lastCommandTime;
}

bool HBM34Core::isSerializable() const
{
    return m_implicitCommands.implicitCommandCount() == 0;
}

void HBM34Core::getWindowStats(timestamp_t timestamp, SimulationStats& stats)
{
    m_implicitCommands.processImplicitCommandQueue(*this, timestamp, m_lastCommandTime);
    stats.bank.resize(m_spec.pseudoChannels * m_spec.banksPerPseudoChannel);
    stats.rank_total.resize(m_spec.pseudoChannels);

    for (std::size_t pc = 0; pc < m_spec.pseudoChannels; ++pc)
    {
        const auto& pseudoChannel = m_pseudoChannels[pc];
        const auto offset = pc * m_spec.banksPerPseudoChannel;
        for (std::size_t bank = 0; bank < m_spec.banksPerPseudoChannel; ++bank)
        {
            auto& output = stats.bank[offset + bank];
            output.counter = pseudoChannel.banks[bank].counter;
            output.cycles.act = pseudoChannel.banks[bank].cycles.act.get_count_at(timestamp);
            output.cycles.pre = timestamp - output.cycles.act;
        }
        stats.rank_total[pc].cycles.act = pseudoChannel.cycles.act.get_count_at(timestamp);
        stats.rank_total[pc].cycles.pre = timestamp - stats.rank_total[pc].cycles.act;
    }
}

} // namespace DRAMPower
