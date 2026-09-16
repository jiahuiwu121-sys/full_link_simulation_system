#ifndef DRAMPOWER_MEMSPEC_MEMSPECHBM34_H
#define DRAMPOWER_MEMSPEC_MEMSPECHBM34_H

#include <DRAMUtils/util/json.h>

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace DRAMPower
{

// Common, self-contained HBM3/HBM4 memory specification.  DRAMUtils v1.16
// does not expose HBM3/HBM4 variants, so these standards are parsed locally.
// All electrical inputs use SI units (V, A, J) and all public timing inputs
// use full CK cycles.  Internally the model converts timings to timestamp ticks.
class MemSpecHBM34
{
public:
    enum VoltageDomain : std::size_t
    {
        VDD = 0,
        VPP = 1,
    };

    struct MemTimingSpec
    {
        double tCK = 0.0;      // physical CK period [s]
        double timeUnit = 0.0; // one command timestamp tick [s]
        uint64_t ticksPerCK = 2;

        uint64_t tRAS = 0;
        uint64_t tRTP = 0;
        uint64_t tWL = 0;
        uint64_t tWR = 0;
        uint64_t tRP = 0;
        uint64_t tRCDRD = 0;
        uint64_t tRCDWR = 0;
        uint64_t tRFC = 0;
        uint64_t tRFCPB = 0;
        uint64_t tRFMAB = 0;
        uint64_t tRFMPB = 0;
        uint64_t tBurst = 0;
    };

    struct MemPowerSpec
    {
        double voltage = 0.0;
        double i0 = 0.0;
        double i2N = 0.0;
        double i3N = 0.0;
        double i4R = 0.0;
        double i4W = 0.0;
        double i5AB = 0.0;
        double i5PB = 0.0;
        double i6N = 0.0;
        double i2P = 0.0;
        double i3P = 0.0;
        double iBeta = 0.0;
        std::optional<double> iRFMAB;
        std::optional<double> iRFMPB;
    };

    struct DataPatternSpec
    {
        bool enabled = false;
        double floorPjPerBit = 2.759;
        double coefficientDQ = 1.192;
        double coefficientTSV = 1.331;
        double coefficientBG = 0.720;
        double dqRate = 0.0;
        double tsvRate = 0.0;
        double bgRate = 0.0;
        double referenceDQRate = 0.0;
        double referenceTSVRate = 0.0;
        double referenceBGRate = 0.0;
        bool applyToWrites = true;

        double activityEnergy(double dq, double tsv, double bg) const;
        double scale() const;
        double effectiveCurrent(double baseCurrent, double backgroundCurrent) const;
    };

    struct InterfacePowerSpec
    {
        // Optional external-link estimate.  Zero leaves interface energy disabled;
        // this prevents double counting when calibrated IDD4 currents include I/O.
        double readEnergyPerBit = 0.0;
        double writeEnergyPerBit = 0.0;
    };

    struct ModelMetadata
    {
        std::string modelKind = "estimated";
        std::string parameterSource = "unspecified";
        std::string reference;
        std::string scope = "per_pseudo_channel";
        std::string notes;
        bool absoluteAccuracyValidated = false;
    };

    virtual ~MemSpecHBM34() = default;

    uint64_t numberOfChannels = 1;
    uint64_t numberOfPseudoChannels = 2;
    uint64_t numberOfSIDs = 1;
    uint64_t numberOfBankGroups = 1;
    uint64_t numberOfBanksPerGroup = 1;
    uint64_t numberOfBanks = 1; // total banks per pseudo-channel
    uint64_t numberOfRows = 0;
    uint64_t numberOfColumns = 0;
    uint64_t numberOfDevices = 1;
    uint64_t burstLength = 8;
    uint64_t dataRate = 4; // transfers per physical CK
    uint64_t bitWidth = 32;

    uint64_t prechargeOffsetRD = 0;
    uint64_t prechargeOffsetWR = 0;

    double vddq = 0.0;
    double bankWiseRho = 1.0;
    double rfmAbPowerRatio = 1.0;
    double rfmPbPowerRatio = 1.0;

    std::string memoryId;
    std::string memoryType;
    MemTimingSpec memTimingSpec;
    std::vector<MemPowerSpec> memPowerSpec;
    DataPatternSpec dataPattern;
    InterfacePowerSpec interfacePower;
    ModelMetadata metadata;

    std::size_t flattenBank(std::size_t sid, std::size_t bankGroup, std::size_t bank) const;

protected:
    MemSpecHBM34(const json_t& data, const std::string& expectedType);
};

} // namespace DRAMPower

#endif /* DRAMPOWER_MEMSPEC_MEMSPECHBM34_H */
