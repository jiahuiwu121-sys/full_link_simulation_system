#include "MemSpecHBM34.h"

#include <cmath>
#include <stdexcept>

namespace DRAMPower
{

namespace
{

uint64_t scaledCycles(const json_t& timing, const char* key, uint64_t ticksPerCK)
{
    return timing.at(key).get<uint64_t>() * ticksPerCK;
}

double optionalNumber(const json_t& object, const char* key, double fallback)
{
    return object.contains(key) ? object.at(key).get<double>() : fallback;
}

void parseDomain(MemSpecHBM34::MemPowerSpec& dst,
                 const json_t& power,
                 const char* voltagePrefix,
                 const char* currentPrefix)
{
    const std::string v = voltagePrefix;
    const std::string i = currentPrefix;
    dst.voltage = optionalNumber(power, v.c_str(), 0.0);
    dst.i0 = optionalNumber(power, (i + "0").c_str(), 0.0);
    dst.i2N = optionalNumber(power, (i + "2n").c_str(), 0.0);
    dst.i3N = optionalNumber(power, (i + "3n").c_str(), 0.0);
    dst.i4R = optionalNumber(power, (i + "4r").c_str(), 0.0);
    dst.i4W = optionalNumber(power, (i + "4w").c_str(), 0.0);
    dst.i5AB = optionalNumber(power, (i + "5ab").c_str(), 0.0);
    dst.i5PB = optionalNumber(power, (i + "5pb").c_str(), 0.0);
    dst.i6N = optionalNumber(power, (i + "6n").c_str(), 0.0);
    dst.i2P = optionalNumber(power, (i + "2p").c_str(), 0.0);
    dst.i3P = optionalNumber(power, (i + "3p").c_str(), 0.0);
    dst.iBeta = optionalNumber(power, (i + "Beta").c_str(), dst.i0);
    if (power.contains(i + "rfmab"))
        dst.iRFMAB = power.at(i + "rfmab").get<double>();
    if (power.contains(i + "rfmpb"))
        dst.iRFMPB = power.at(i + "rfmpb").get<double>();
}

} // namespace

double MemSpecHBM34::DataPatternSpec::activityEnergy(double dq, double tsv, double bg) const
{
    return floorPjPerBit + dq * coefficientDQ + tsv * coefficientTSV + bg * coefficientBG;
}

double MemSpecHBM34::DataPatternSpec::scale() const
{
    const double reference = activityEnergy(referenceDQRate, referenceTSVRate, referenceBGRate);
    return reference > 0.0 ? activityEnergy(dqRate, tsvRate, bgRate) / reference : 1.0;
}

double MemSpecHBM34::DataPatternSpec::effectiveCurrent(double baseCurrent,
                                                       double backgroundCurrent) const
{
    if (!enabled)
        return baseCurrent;
    return backgroundCurrent + (baseCurrent - backgroundCurrent) * scale();
}

MemSpecHBM34::MemSpecHBM34(const json_t& data, const std::string& expectedType) :
    memoryId(data.value("memoryId", expectedType + "_estimated")),
    memoryType(data.at("memoryType").get<std::string>()),
    memPowerSpec(2)
{
    if (memoryType != expectedType)
    {
        throw std::invalid_argument("Expected memoryType " + expectedType + ", got " + memoryType);
    }

    const auto& arch = data.at("memarchitecturespec");
    numberOfChannels = arch.value("nbrOfChannels", 1ULL);
    numberOfPseudoChannels = arch.at("nbrOfPseudoChannels").get<uint64_t>();
    numberOfSIDs = arch.at("nbrOfSIDs").get<uint64_t>();
    numberOfBankGroups = arch.at("nbrOfBankGroups").get<uint64_t>();
    numberOfBanksPerGroup = arch.at("nbrOfBanksPerGroup").get<uint64_t>();
    numberOfRows = arch.at("nbrOfRows").get<uint64_t>();
    numberOfColumns = arch.at("nbrOfColumns").get<uint64_t>();
    numberOfDevices = arch.value("nbrOfDevices", 1ULL);
    burstLength = arch.value("burstLength", 8ULL);
    dataRate = arch.value("dataRate", 4ULL);
    bitWidth = arch.value("width", 32ULL);

    if (numberOfChannels == 0 || numberOfPseudoChannels == 0 || numberOfSIDs == 0 ||
        numberOfBankGroups == 0 || numberOfBanksPerGroup == 0 || numberOfDevices == 0 ||
        bitWidth == 0 || dataRate == 0)
    {
        throw std::invalid_argument("HBM3/HBM4 architecture counts must be positive");
    }
    if (numberOfChannels != 1)
    {
        throw std::invalid_argument(
            "One HBM3/HBM4 model instance represents one channel; nbrOfChannels must be 1");
    }
    numberOfBanks = numberOfSIDs * numberOfBankGroups * numberOfBanksPerGroup;

    const auto& timing = data.at("memtimingspec");
    memTimingSpec.tCK = timing.at("tCK").get<double>();
    memTimingSpec.ticksPerCK = timing.value("ticksPerCK", 2ULL);
    if (memTimingSpec.tCK <= 0.0 || memTimingSpec.ticksPerCK == 0)
    {
        throw std::invalid_argument("HBM3/HBM4 tCK and ticksPerCK must be positive");
    }
    memTimingSpec.timeUnit = memTimingSpec.tCK / static_cast<double>(memTimingSpec.ticksPerCK);
    memTimingSpec.tRAS = scaledCycles(timing, "RAS", memTimingSpec.ticksPerCK);
    memTimingSpec.tRTP = scaledCycles(timing, "RTP", memTimingSpec.ticksPerCK);
    memTimingSpec.tWL = scaledCycles(timing, "WL", memTimingSpec.ticksPerCK);
    memTimingSpec.tWR = scaledCycles(timing, "WR", memTimingSpec.ticksPerCK);
    memTimingSpec.tRP = scaledCycles(timing, "RP", memTimingSpec.ticksPerCK);
    memTimingSpec.tRCDRD = scaledCycles(timing, "RCDRD", memTimingSpec.ticksPerCK);
    memTimingSpec.tRCDWR = scaledCycles(timing, "RCDWR", memTimingSpec.ticksPerCK);
    memTimingSpec.tRFC = scaledCycles(timing, "RFC", memTimingSpec.ticksPerCK);
    memTimingSpec.tRFCPB = scaledCycles(timing, "RFCPB", memTimingSpec.ticksPerCK);
    memTimingSpec.tRFMAB = scaledCycles(timing, "RFMAB", memTimingSpec.ticksPerCK);
    memTimingSpec.tRFMPB = scaledCycles(timing, "RFMPB", memTimingSpec.ticksPerCK);

    const uint64_t numerator = burstLength * memTimingSpec.ticksPerCK;
    if (numerator % dataRate != 0)
    {
        throw std::invalid_argument(
            "HBM3/HBM4 burstLength*ticksPerCK must be divisible by dataRate");
    }
    memTimingSpec.tBurst = numerator / dataRate;
    prechargeOffsetRD = memTimingSpec.tRTP;
    prechargeOffsetWR = memTimingSpec.tBurst + memTimingSpec.tWL + memTimingSpec.tWR;

    const auto& power = data.at("mempowerspec");
    parseDomain(memPowerSpec[VDD], power, "vdd", "idd");
    parseDomain(memPowerSpec[VPP], power, "vpp", "ipp");
    vddq = power.value("vddq", memPowerSpec[VDD].voltage);
    bankWiseRho = power.value("bankWiseRho", 1.0);
    rfmAbPowerRatio = power.value("rfmAbPowerRatio", 1.0);
    rfmPbPowerRatio = power.value("rfmPbPowerRatio", 1.0);

    if (data.contains("datapattern"))
    {
        const auto& pattern = data.at("datapattern");
        dataPattern.enabled = pattern.value("enabled", false);
        dataPattern.floorPjPerBit = pattern.value("floorPjPerBit", dataPattern.floorPjPerBit);
        dataPattern.coefficientDQ = pattern.value("coefficientDQ", dataPattern.coefficientDQ);
        dataPattern.coefficientTSV = pattern.value("coefficientTSV", dataPattern.coefficientTSV);
        dataPattern.coefficientBG = pattern.value("coefficientBG", dataPattern.coefficientBG);
        dataPattern.dqRate = pattern.value("dqRate", dataPattern.dqRate);
        dataPattern.tsvRate = pattern.value("tsvRate", dataPattern.tsvRate);
        dataPattern.bgRate = pattern.value("bgRate", dataPattern.bgRate);
        dataPattern.referenceDQRate = pattern.value("referenceDQRate", dataPattern.referenceDQRate);
        dataPattern.referenceTSVRate =
            pattern.value("referenceTSVRate", dataPattern.referenceTSVRate);
        dataPattern.referenceBGRate = pattern.value("referenceBGRate", dataPattern.referenceBGRate);
        dataPattern.applyToWrites = pattern.value("applyToWrites", dataPattern.applyToWrites);
    }

    if (data.contains("interfacepowerspec"))
    {
        const auto& interface = data.at("interfacepowerspec");
        interfacePower.readEnergyPerBit = interface.value("readEnergyPerBit", 0.0);
        interfacePower.writeEnergyPerBit = interface.value("writeEnergyPerBit", 0.0);
    }

    if (data.contains("modelMetadata"))
    {
        const auto& model = data.at("modelMetadata");
        metadata.modelKind = model.value("modelKind", metadata.modelKind);
        metadata.parameterSource = model.value("parameterSource", metadata.parameterSource);
        metadata.reference = model.value("reference", metadata.reference);
        metadata.scope = model.value("scope", metadata.scope);
        metadata.notes = model.value("notes", metadata.notes);
        metadata.absoluteAccuracyValidated = model.value("absoluteAccuracyValidated", false);
    }
}

std::size_t
MemSpecHBM34::flattenBank(std::size_t sid, std::size_t bankGroup, std::size_t bank) const
{
    if (sid >= numberOfSIDs || bankGroup >= numberOfBankGroups || bank >= numberOfBanksPerGroup)
    {
        throw std::out_of_range("HBM3/HBM4 bank coordinate out of range");
    }
    return (sid * numberOfBankGroups + bankGroup) * numberOfBanksPerGroup + bank;
}

} // namespace DRAMPower
