#include "run.hpp"

#include <memory>
#include <vector>
#include <fstream>
#include <exception>
#include <string>

#include <spdlog/spdlog.h>
#include <spdlog/fmt/ostr.h>

#include <DRAMPower/Types.h>

#include <DRAMPower/dram/dram_base.h>

#include <DRAMPower/data/energy.h>

#include <DRAMPower/util/cli_architecture_config.h>

#include <DRAMPower/standards/lpddr4/LPDDR4.h>
#include <DRAMPower/memspec/MemSpecLPDDR4.h>
#include <DRAMUtils/memspec/standards/MemSpecLPDDR4.h>

#include <DRAMPower/standards/lpddr5/LPDDR5.h>
#include <DRAMPower/memspec/MemSpecLPDDR5.h>
#include <DRAMUtils/memspec/standards/MemSpecLPDDR5.h>

#include <DRAMPower/standards/lpddr6/LPDDR6.h>
#include <DRAMPower/memspec/MemSpecLPDDR6.h>
#include <DRAMUtils/memspec/standards/MemSpecLPDDR6.h>

#include <DRAMPower/standards/hbm2/HBM2.h>
#include <DRAMPower/memspec/MemSpecHBM2.h>
#include <DRAMUtils/memspec/standards/MemSpecHBM2.h>

#include <DRAMPower/standards/hbm3/HBM3.h>
#include <DRAMPower/memspec/MemSpecHBM3.h>
#include <DRAMPower/standards/hbm4/HBM4.h>
#include <DRAMPower/memspec/MemSpecHBM4.h>
#include <DRAMPower/standards/hbm34/HBM34.h>

#include <DRAMUtils/util/json_utils.h>
#include <DRAMUtils/memspec/MemSpec.h>

#include "csv.hpp"
#include "util.hpp"
#include "config.h"

namespace DRAMPower::DRAMPowerCLI {

using namespace DRAMPower;

std::unique_ptr<dram_base<CmdType>> getMemory(const std::string_view &data, const DRAMPower::config::SimConfig& simconfig)
{
	try
	{
		std::unique_ptr<dram_base<CmdType>> result = nullptr;
		// HBM3/HBM4 are parsed locally because DRAMUtils v1.16 has no variants for them.
		{
			std::ifstream input{std::string(data)};
			if (!input.is_open()) return nullptr;
			json_t root = json_t::parse(input);
			const auto type = root.value("memoryType", std::string{});
			if (type == "HBM3") return std::make_unique<HBM3>(MemSpecHBM3(root));
			if (type == "HBM4") return std::make_unique<HBM4>(MemSpecHBM4(root));
		}
		// Get memspec
        auto memspec = DRAMUtils::parse_memspec_from_file(std::filesystem::path(data));
        if (!memspec) {
            return result;
		}
		// Get ddr
		std::visit( [&result, &simconfig] (auto&& arg) {
			using T = std::decay_t<decltype(arg)>;
			if constexpr (std::is_same_v<T, DRAMUtils::MemSpec::MemSpecLPDDR4>)
			{
				MemSpecLPDDR4 ddr (static_cast<DRAMUtils::MemSpec::MemSpecLPDDR4>(arg));
				result = std::make_unique<LPDDR4>(ddr, simconfig);
			}
			else if constexpr (std::is_same_v<T, DRAMUtils::MemSpec::MemSpecLPDDR5>)
			{
				MemSpecLPDDR5 ddr (static_cast<DRAMUtils::MemSpec::MemSpecLPDDR5>(arg));
				result = std::make_unique<LPDDR5>(ddr, simconfig);
			}
			else if constexpr (std::is_same_v<T, DRAMUtils::MemSpec::MemSpecLPDDR6>)
			{
				MemSpecLPDDR6 ddr (static_cast<DRAMUtils::MemSpec::MemSpecLPDDR6>(arg));
				result = std::make_unique<LPDDR6>(ddr, simconfig);
			}
			else if constexpr (std::is_same_v<T, DRAMUtils::MemSpec::MemSpecHBM2>)
			{
				MemSpecHBM2 ddr (static_cast<DRAMUtils::MemSpec::MemSpecHBM2>(arg));
				result = std::make_unique<HBM2>(ddr, simconfig);
			}
		}, memspec->getVariant());

		return result;
	}
	catch(const std::exception& e)
	{
		return nullptr;
	}
}

bool parse_command_list(std::string_view csv_file, std::vector<std::pair<Command, std::unique_ptr<uint8_t[]>>> &commandList)
{
	// Read csv file
	csv::CSVFormat format;
	format.no_header();
	format.trim({ ' ', '\t' });

	csv::CSVReader reader{ csv_file, format };
	
	// loop variables
	std::size_t rowidx, size, rank_id, bank_group_id, bank_id, row_id, column_id = 0;
	std::size_t channel_id, pseudo_channel_id, sid_id = 0;

	timestamp_t timestamp = 0;
	csv::string_view cmdType;
	std::unordered_map<csv::string_view, DRAMPower::CmdType>::iterator cmdit;
	CmdType cmd;

	// Parse csv file
	// Legacy: timestamp, command, rank, bank_group, bank, row, column, [data]
	// HBM3/4: timestamp, command, channel, pseudo_channel, sid, bank_group, bank, row, column, [data]
	constexpr std::size_t MINCSVSIZE = 7;
	for ( csv::CSVRow& row : reader ) {
		rowidx = 0;

		// Read csv row
		if ( row.size() < MINCSVSIZE )
		{
            return false;
		}
			
		timestamp = row[rowidx++].get<timestamp_t>();
		cmdType = row[rowidx++].get_sv();
		const bool extendedHBMCoordinate = row.size() >= 9;
		if (extendedHBMCoordinate) {
			channel_id = row[rowidx++].get<std::size_t>();
			pseudo_channel_id = row[rowidx++].get<std::size_t>();
			sid_id = row[rowidx++].get<std::size_t>();
			rank_id = 0;
			bank_group_id = row[rowidx++].get<std::size_t>();
			bank_id = row[rowidx++].get<std::size_t>();
			row_id = row[rowidx++].get<std::size_t>();
			column_id = row[rowidx++].get<std::size_t>();
		} else {
			channel_id = pseudo_channel_id = sid_id = 0;
			rank_id = row[rowidx++].get<std::size_t>();
			bank_group_id = row[rowidx++].get<std::size_t>();
			bank_id = row[rowidx++].get<std::size_t>();
			row_id = row[rowidx++].get<std::size_t>();
			column_id = row[rowidx++].get<std::size_t>();
		}

		// Get command
		cmd = DRAMPower::CmdTypeUtil::from_string(cmdType);

		// Get data if needed
		if ( DRAMPower::CmdTypeUtil::needs_data(cmd) ) {
			if ( row.size() < (extendedHBMCoordinate ? 10U : MINCSVSIZE + 1) ) {
                return false;
			}
			// uint64_t length = 0;
			csv::string_view data = row[rowidx++].get_sv();
			std::unique_ptr<uint8_t[]> arr;
			try
			{
				arr = util::hexStringToUint8Array(data, size);
			}
			catch (std::exception &e)
			{
                return false;
			}
			commandList.emplace_back(Command{timestamp, cmd,
				{bank_id, bank_group_id, rank_id, row_id, column_id, pseudo_channel_id, sid_id, channel_id},
				arr.get(), size * 8}, std::move(arr));
		}
		else {
			commandList.emplace_back(Command{timestamp, cmd,
				{bank_id, bank_group_id, rank_id, row_id, column_id, pseudo_channel_id, sid_id, channel_id}}, nullptr);
		}
	}

	return true;
};

bool jsonFileResult(const std::string &jsonfile, const std::unique_ptr<dram_base<CmdType>> &ddr, const energy_t &core_energy, const interface_energy_info_t &interface_energy)
{
	std::ofstream out;
	out = std::ofstream(jsonfile);
	if ( !out.is_open() ) {
        return false;
	}
	json_t j;
	size_t energy_offset = 0;
	DRAMPower::util::CLIArchitectureConfig cli_config = ddr->getCLIArchitectureConfig();
	auto bankcount = cli_config.bankCount;
	auto rankcount = cli_config.rankCount;
	auto devicecount = cli_config.deviceCount;

	j["RankCount"] = rankcount;
	j["DeviceCount"] = devicecount;
	j["BankCount"] = bankcount;
	j["TotalEnergy"] = core_energy.total() + interface_energy.total();
	if (const auto* hbm = dynamic_cast<const HBM34*>(ddr.get())) {
		const double duration = ddr->getLastCommandTime() * hbm->getMemSpec().memTimingSpec.timeUnit;
		j["Model"] = {
			{"MemoryId", hbm->getMemSpec().memoryId},
			{"MemoryType", hbm->getMemSpec().memoryType},
			{"ModelKind", hbm->getMemSpec().metadata.modelKind},
			{"ParameterSource", hbm->getMemSpec().metadata.parameterSource},
			{"Reference", hbm->getMemSpec().metadata.reference},
			{"Scope", hbm->getMemSpec().metadata.scope},
			{"Notes", hbm->getMemSpec().metadata.notes},
			{"AbsoluteAccuracyValidated", hbm->getMemSpec().metadata.absoluteAccuracyValidated}
		};
		j["SimulationDurationSeconds"] = duration;
		j["AveragePowerWatts"] = duration > 0.0 ? j["TotalEnergy"].get<double>() / duration : 0.0;
		j["Organization"] = {
			{"PseudoChannels", hbm->getMemSpec().numberOfPseudoChannels},
			{"SIDsPerPseudoChannel", hbm->getMemSpec().numberOfSIDs},
			{"BankGroupsPerSID", hbm->getMemSpec().numberOfBankGroups},
			{"BanksPerGroup", hbm->getMemSpec().numberOfBanksPerGroup}
		};
	}

	// Energy object to json
	core_energy.to_json(j["CoreEnergy"]);
	interface_energy.to_json(j["InterfaceEnergy"]);

	// Validate array length
	if ( !j["CoreEnergy"][core_energy.get_Bank_energy_keyword()].is_array() || j["CoreEnergy"][core_energy.get_Bank_energy_keyword()].size() != rankcount * bankcount * devicecount )
	{
		assert(false); // (should not happen)
        return false;
	}
	
	// Add rank,device,bank description
	for ( std::size_t r = 0; r < rankcount; r++ ) {
		for ( std::size_t d = 0; d < devicecount; d++ ) {
			energy_offset = r * bankcount * devicecount + d * bankcount;
			for ( std::size_t b = 0; b < bankcount; b++ ) {
				// Rank,Device,Bank -> bank_energy
				j["CoreEnergy"][core_energy.get_Bank_energy_keyword()].at(energy_offset + b)["Rank"] = r;
				j["CoreEnergy"][core_energy.get_Bank_energy_keyword()].at(energy_offset + b)["Device"] = d;
				j["CoreEnergy"][core_energy.get_Bank_energy_keyword()].at(energy_offset + b)["Bank"] = b;
				if (const auto* hbm = dynamic_cast<const HBM34*>(ddr.get())) {
					const auto banksPerSID = hbm->getMemSpec().numberOfBankGroups *
						hbm->getMemSpec().numberOfBanksPerGroup;
					auto& bankJson = j["CoreEnergy"][core_energy.get_Bank_energy_keyword()].at(energy_offset + b);
					bankJson["PseudoChannel"] = r;
					bankJson["SID"] = b / banksPerSID;
					bankJson["BankGroup"] = (b % banksPerSID) / hbm->getMemSpec().numberOfBanksPerGroup;
					bankJson["BankInGroup"] = b % hbm->getMemSpec().numberOfBanksPerGroup;
				}
			}
		}
	}
	
	out << j.dump(4) << std::endl;
	out.close();
	return true;
}

bool stdoutResult(const std::unique_ptr<dram_base<CmdType>> &ddr, const energy_t &core_energy, const interface_energy_info_t &interface_energy)
{
	// Setup output format
	std::cout << std::defaultfloat << std::setprecision(3);
	// Print stats
	DRAMPower::util::CLIArchitectureConfig cli_config = ddr->getCLIArchitectureConfig();
	auto bankcount = cli_config.bankCount;
	auto rankcount = cli_config.rankCount;
	auto devicecount = cli_config.deviceCount;
	size_t energy_offset = 0;
	// NOTE: ensure the same order of calculation in the interface
	spdlog::info("Rank,Device,Bank -> bank_energy:");
	for ( std::size_t r = 0; r < rankcount; r++ ) {
		for ( std::size_t d = 0; d < devicecount; d++ ) {
			energy_offset = r * bankcount * devicecount + d * bankcount;
			for ( std::size_t b = 0; b < bankcount; b++ ) {
				// Rank,Device,Bank -> bank_energy
				spdlog::info("{},{},{} -> {}",
					r, d, b,
					core_energy.bank_energy[energy_offset + b]
				);
			}
		}
	}
	spdlog::info("Cumulated bank energy with bg_act_shared -> {}", core_energy.aggregated_bank_energy());
	spdlog::info("Shared energy -> {}", core_energy);
	spdlog::info("Interface Energy:\n{}", interface_energy);
	spdlog::info("Total Energy -> {}", core_energy.total() + interface_energy.total());
	if (const auto* hbm = dynamic_cast<const HBM34*>(ddr.get())) {
		const double duration = ddr->getLastCommandTime() * hbm->getMemSpec().memTimingSpec.timeUnit;
		spdlog::info("Model -> {} ({})", hbm->getMemSpec().memoryId, hbm->getMemSpec().metadata.modelKind);
		spdlog::info("Simulation Duration [s] -> {}", duration);
		spdlog::info("Average Power [W] -> {}", duration > 0.0
			? (core_energy.total() + interface_energy.total()) / duration : 0.0);
	}
	return true;
}

bool getConfig(const std::string &configfile, config::CLIConfig &config)
{
    try {
        std::ifstream file(configfile);
        if (!file.is_open()) {
            return false;
        }
        json_t json_obj = json_t::parse(file, nullptr, false, true);
        config = json_obj;
        if (!config.useToggleRate) {
            config.simconfig.toggleRateDefinition = std::nullopt;
        }
        if (config.useToggleRate && !config.simconfig.toggleRateDefinition.has_value()) {
            spdlog::error("Provide a toggleRateDefinition for a simulation with toggling rates");
            return false;
        }
    } catch (std::exception&) {
        return false;
    }
    return true;
}

bool makeResult(std::optional<std::string> jsonfile, const std::unique_ptr<dram_base<CmdType>> &ddr)
{
    energy_t core_energy = ddr->calcCoreEnergy(ddr->getLastCommandTime());
    interface_energy_info_t interface_energy = ddr->calcInterfaceEnergy(ddr->getLastCommandTime());
    if(jsonfile)
	{
		return jsonFileResult(*jsonfile, std::move(ddr), core_energy, interface_energy);
	}
	else
	{
		return stdoutResult(std::move(ddr), core_energy, interface_energy);
	}
}

bool runCommands(std::unique_ptr<dram_base<CmdType>> &ddr, const std::vector<std::pair<Command, std::unique_ptr<uint8_t[]>>> &commandList)
{
    try {
		for (auto &command : commandList ) {
			ddr->doCommand(command.first);
		}
	} catch (std::exception &e) {
		return false;
	}
    return true;
}

} // namespace DRAMPower::DRAMPowerCLI
