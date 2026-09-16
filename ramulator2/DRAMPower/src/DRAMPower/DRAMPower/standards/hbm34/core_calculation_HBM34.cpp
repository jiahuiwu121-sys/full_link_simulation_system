#include "core_calculation_HBM34.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace DRAMPower
{

namespace
{

double nonNegative(double value)
{
    return std::max(0.0, value);
}

} // namespace

energy_t Calculation_HBM34::calcEnergy(const SimulationStats& stats) const
{
    const auto pseudoChannels = m_spec.numberOfPseudoChannels;
    const auto banks = m_spec.numberOfBanks;
    const auto devices = m_spec.numberOfDevices;
    if (stats.bank.size() != pseudoChannels * banks || stats.rank_total.size() != pseudoChannels)
    {
        throw std::invalid_argument("HBM3/HBM4 statistics do not match the memory organization");
    }

    energy_t energy(pseudoChannels * devices * banks);
    const double tick = m_spec.memTimingSpec.timeUnit;
    const double tRAS = m_spec.memTimingSpec.tRAS * tick;
    const double tRP = m_spec.memTimingSpec.tRP * tick;
    const double tRFC = m_spec.memTimingSpec.tRFC * tick;
    const double tRFCPB = m_spec.memTimingSpec.tRFCPB * tick;
    const double tRFMAB = m_spec.memTimingSpec.tRFMAB * tick;
    const double tRFMPB = m_spec.memTimingSpec.tRFMPB * tick;
    const double burstTime = m_spec.memTimingSpec.tBurst * tick;

    for (std::size_t voltageDomain = 0; voltageDomain < m_spec.memPowerSpec.size(); ++voltageDomain)
    {
        const auto& power = m_spec.memPowerSpec[voltageDomain];
        const double voltage = power.voltage;
        if (voltage == 0.0)
            continue;

        const double rho = m_spec.bankWiseRho;
        const double denominator = banks * rho + 1.0 - rho;
        const double iRho = denominator > 0.0
                                ? (banks * rho * power.i3N + (1.0 - rho) * power.i2N) / denominator
                                : power.i3N;
        const double iAllBanksActive = iRho + banks * (power.i3N - iRho);
        const double iTheta =
            tRAS > 0.0 ? (power.i0 * (tRP + tRAS) - power.iBeta * tRP) / tRAS : power.i0;
        const double readDynamicCurrent = nonNegative(power.i4R - iAllBanksActive);
        const double writeDynamicCurrent = nonNegative(power.i4W - iAllBanksActive);
        double readVoltageFactor = voltage;
        double writeVoltageFactor = voltage;
        if (voltageDomain == MemSpecHBM34::VDD && m_spec.dataPattern.enabled)
        {
            const auto& pattern = m_spec.dataPattern;
            const double reference = pattern.activityEnergy(
                pattern.referenceDQRate, pattern.referenceTSVRate, pattern.referenceBGRate);
            if (reference > 0.0)
            {
                const double coreTerms = pattern.floorPjPerBit +
                                         pattern.tsvRate * pattern.coefficientTSV +
                                         pattern.bgRate * pattern.coefficientBG;
                const double dqTerms = pattern.dqRate * pattern.coefficientDQ;
                readVoltageFactor = (voltage * coreTerms + m_spec.vddq * dqTerms) / reference;
                if (pattern.applyToWrites)
                    writeVoltageFactor = voltage * pattern.scale();
            }
        }

        const double refreshAbCurrent = power.i5AB > 0.0 ? power.i5AB : power.i0;
        const double refreshPbCurrent = power.i5PB > 0.0 ? power.i5PB : power.i0;
        const double rfmAbCurrent = power.iRFMAB.value_or(
            iAllBanksActive + (refreshAbCurrent - iAllBanksActive) * m_spec.rfmAbPowerRatio);
        const double rfmPbCurrent = power.iRFMPB.value_or(
            power.i3N + (refreshPbCurrent - power.i3N) * m_spec.rfmPbPowerRatio);

        for (std::size_t pc = 0; pc < pseudoChannels; ++pc)
        {
            const auto statsOffset = pc * banks;
            for (std::size_t device = 0; device < devices; ++device)
            {
                const auto energyOffset = (pc * devices + device) * banks;
                for (std::size_t bankIndex = 0; bankIndex < banks; ++bankIndex)
                {
                    const auto& bank = stats.bank[statsOffset + bankIndex];
                    auto& bankEnergy = energy.bank_energy[energyOffset + bankIndex];

                    bankEnergy.E_act +=
                        voltage * nonNegative(iTheta - power.i3N) * tRAS * bank.counter.act;
                    bankEnergy.E_pre +=
                        voltage * nonNegative(power.iBeta - power.i2N) * tRP * bank.counter.pre;
                    bankEnergy.E_bg_act +=
                        voltage * nonNegative(power.i3N - iRho) * bank.cycles.act * tick;
                    bankEnergy.E_bg_pre += voltage * power.i2N * stats.rank_total[pc].cycles.pre *
                                           tick / static_cast<double>(banks);
                    bankEnergy.E_RD +=
                        readVoltageFactor * readDynamicCurrent * burstTime * bank.counter.reads;
                    bankEnergy.E_WR +=
                        writeVoltageFactor * writeDynamicCurrent * burstTime * bank.counter.writes;
                    bankEnergy.E_RDA +=
                        readVoltageFactor * readDynamicCurrent * burstTime * bank.counter.readAuto;
                    bankEnergy.E_WRA += writeVoltageFactor * writeDynamicCurrent * burstTime *
                                        bank.counter.writeAuto;
                    bankEnergy.E_pre_RDA += voltage * nonNegative(power.iBeta - power.i2N) * tRP *
                                            bank.counter.readAuto;
                    bankEnergy.E_pre_WRA += voltage * nonNegative(power.iBeta - power.i2N) * tRP *
                                            bank.counter.writeAuto;
                    bankEnergy.E_ref_AB += voltage *
                                           nonNegative(refreshAbCurrent - iAllBanksActive) * tRFC *
                                           bank.counter.refAllBank / static_cast<double>(banks);
                    bankEnergy.E_ref_PB += voltage * nonNegative(refreshPbCurrent - power.i3N) *
                                           tRFCPB * bank.counter.refPerBank;
                    bankEnergy.E_RFM_AB += voltage * nonNegative(rfmAbCurrent - iAllBanksActive) *
                                           tRFMAB * bank.counter.rfmAllBank /
                                           static_cast<double>(banks);
                    bankEnergy.E_RFM_PB += voltage * nonNegative(rfmPbCurrent - power.i3N) *
                                           tRFMPB * bank.counter.rfmPerBank;
                }
            }

            energy.E_bg_act_shared +=
                voltage * iRho * stats.rank_total[pc].cycles.act * tick * devices;
            energy.E_sref +=
                voltage * power.i6N * stats.rank_total[pc].cycles.selfRefresh * tick * devices;
            energy.E_PDNA +=
                voltage * power.i3P * stats.rank_total[pc].cycles.powerDownAct * tick * devices;
            energy.E_PDNP +=
                voltage * power.i2P * stats.rank_total[pc].cycles.powerDownPre * tick * devices;
        }
    }

    return energy;
}

} // namespace DRAMPower
