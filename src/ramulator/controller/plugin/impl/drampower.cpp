#include <DRAMPower/command/Command.h>
#include <DRAMPower/data/energy.h>
#include <DRAMPower/dram/dram_base.h>
#include <DRAMPower/factory/MemoryFactory.h>
#include <DRAMPower/standards/hbm34/HBM34.h>
#include <DRAMPower/standards/lpddr5/LPDDR5.h>
#include <DRAMPower/standards/lpddr6/LPDDR6.h>
#include <DRAMUtils/config/toggling_rate.h>
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <stdexcept>
#include <string>
#include <unordered_map>

#include "ramulator/base/base.h"
#include "ramulator/base/param.h"
#include "ramulator/controller/controller_base.h"
#include "ramulator/controller/plugin/i_controller_plugin.h"
#include "ramulator/controller/plugin/power_reporter.h"
#include "ramulator/dram/dram_spec.h"

namespace Ramulator {

class DRAMPowerModel final : public IControllerPlugin, public IPowerReporter, public Implementation {
  RAMULATOR_REGISTER_IMPLEMENTATION(IControllerPlugin, DRAMPowerModel, "DRAMPower")

 public:
  void init() override {
    RAMULATOR_PARSE_PARAM(m_memspec_path, std::string, "memspec_path").required();
    RAMULATOR_PARSE_PARAM(m_strict_validation, bool, "strict_validation").default_val(true);
    RAMULATOR_PARSE_PARAM(m_include_interface, bool, "include_interface").default_val(true);
    RAMULATOR_PARSE_PARAM(m_read_toggle_rate, double, "read_toggle_rate").default_val(0.5);
    RAMULATOR_PARSE_PARAM(m_write_toggle_rate, double, "write_toggle_rate").default_val(0.5);
    RAMULATOR_PARSE_PARAM(m_read_duty_cycle, double, "read_duty_cycle").default_val(0.5);
    RAMULATOR_PARSE_PARAM(m_write_duty_cycle, double, "write_duty_cycle").default_val(0.5);

    validate_probability("read_toggle_rate", m_read_toggle_rate);
    validate_probability("write_toggle_rate", m_write_toggle_rate);
    validate_probability("read_duty_cycle", m_read_duty_cycle);
    validate_probability("write_duty_cycle", m_write_duty_cycle);
  }

  void setup(IFrontEnd*, IMemorySystem*) override {
    m_ctrl = cast_parent<ControllerBase>();
    const auto idle = DRAMUtils::Config::TogglingRateIdlePattern::L;
    DRAMPower::config::SimConfig sim_config{DRAMUtils::Config::ToggleRateDefinition{
        m_read_toggle_rate, m_write_toggle_rate, m_read_duty_cycle, m_write_duty_cycle, idle, idle}};
    m_model = DRAMPower::createMemoryModel(m_memspec_path, sim_config);
    m_standard = m_ctrl->m_device.m_spec->standard_name;
    m_tick_seconds = static_cast<double>(m_ctrl->m_device.m_spec->get_timing_value("tCK_ps")) * 1e-12;

    validate_model();
    cache_level_ids();

    m_stats.add("model", m_standard);
    m_stats.add("duration_seconds", m_visible.duration_seconds);
    m_stats.add("core_energy_j", m_visible.core_energy_j);
    m_stats.add("interface_energy_j", m_visible.interface_energy_j);
    m_stats.add("total_energy_j", m_visible.total_energy_j);
    m_stats.add("average_power_w", m_visible.average_power_w);
    m_stats.add("activation_energy_j", m_visible.activation_energy_j);
    m_stats.add("precharge_energy_j", m_visible.precharge_energy_j);
    m_stats.add("read_energy_j", m_visible.read_energy_j);
    m_stats.add("write_energy_j", m_visible.write_energy_j);
    m_stats.add("refresh_energy_j", m_visible.refresh_energy_j);
    m_stats.add("rfm_energy_j", m_visible.rfm_energy_j);
    m_stats.add("background_energy_j", m_visible.background_energy_j);
    m_stats.add("controller_interface_energy_j", m_visible.controller_interface_energy_j);
    m_stats.add("dram_interface_energy_j", m_visible.dram_interface_energy_j);
    m_stats.add("mapped_commands", m_visible.mapped_commands);
    m_stats.add("ignored_interface_commands", m_visible.ignored_interface_commands);
    m_stats.add("unsupported_commands", m_visible.unsupported_commands);
  }

  void on_issue(const Request& req) override {
    if (m_finalized) {
      throw std::runtime_error("DRAMPower received a command after finalization");
    }

    const std::string& name = m_ctrl->m_device.m_spec->command_names.at(req.command);
    const auto target = target_coordinate(req.addr_vec);

    if (m_standard == "HBM3" || m_standard == "HBM4") {
      issue_mapped(name, target, m_ctrl->m_clk, true);
      return;
    }

    // LPDDR exposes split ACT and WCK synchronization commands. DRAMPower's
    // core consumes one semantic ACT; its current public interface has no CAS
    // synchronization command, so those timing-only markers are audited but
    // intentionally not sent to the core.
    if (name == "ACT1") {
      issue_command(DRAMPower::CmdType::ACT, target, m_ctrl->m_clk, true, false);
      issue_command(DRAMPower::CmdType::ACT1, target, m_ctrl->m_clk, false, true);
      ++m_mapped_total;
      return;
    }
    if (name == "ACT2") {
      issue_command(DRAMPower::CmdType::ACT2, target, m_ctrl->m_clk, false, true);
      ++m_mapped_total;
      return;
    }
    if (name == "CAS" || name == "CAS_RD" || name == "CAS_WR") {
      ++m_ignored_interface_total;
      return;
    }
    if (name.ends_with("_L")) {
      ++m_unsupported_total;
      throw std::runtime_error("DRAMPower LPDDR6 long-burst command '" + name +
                               "' requires a burst-length-aware power memspec; refusing to count it as a short burst");
    }
    issue_mapped(name, target, m_ctrl->m_clk, true);
  }

  void update_stats() override {
    m_visible = power_stats(m_ctrl ? m_ctrl->m_clk : 0);
  }

  void reset_stats() override {
    if (!m_ctrl || !m_model) {
      return;
    }
    m_baseline = cumulative_stats(m_ctrl->m_clk);
    m_baseline_tick = m_ctrl->m_clk;
    m_mapped_baseline = m_mapped_total;
    m_ignored_interface_baseline = m_ignored_interface_total;
    m_unsupported_baseline = m_unsupported_total;
    m_visible = {};
  }

  void finalize() override {
    if (m_ctrl) {
      finalize_power(m_ctrl->m_clk);
    }
  }

  PowerStats power_stats(Clk_t timestamp) override {
    if (!m_model) {
      return {};
    }
    const PowerStats current = cumulative_stats(timestamp);
    PowerStats result = subtract(current, m_baseline);
    result.duration_seconds = static_cast<double>(std::max<Clk_t>(0, timestamp - m_baseline_tick)) * m_tick_seconds;
    result.average_power_w = result.duration_seconds > 0.0 ? result.total_energy_j / result.duration_seconds : 0.0;
    result.mapped_commands = m_mapped_total - m_mapped_baseline;
    result.ignored_interface_commands = m_ignored_interface_total - m_ignored_interface_baseline;
    result.unsupported_commands = m_unsupported_total - m_unsupported_baseline;
    return result;
  }

  void finalize_power(Clk_t timestamp) override {
    if (!m_model || m_finalized) {
      return;
    }
    DRAMPower::Command end{static_cast<DRAMPower::timestamp_t>(timestamp), DRAMPower::CmdType::END_OF_SIMULATION};
    if (m_include_interface) {
      m_model->doCommand(end);
    } else {
      m_model->doCoreCommand(end);
    }
    m_finalized = true;
    m_visible = power_stats(timestamp);
  }

 private:
  ControllerBase* m_ctrl = nullptr;
  std::unique_ptr<DRAMPower::dram_base<DRAMPower::CmdType>> m_model;
  std::string m_memspec_path;
  std::string m_standard;
  bool m_strict_validation = true;
  bool m_include_interface = true;
  bool m_finalized = false;
  double m_read_toggle_rate = 0.5;
  double m_write_toggle_rate = 0.5;
  double m_read_duty_cycle = 0.5;
  double m_write_duty_cycle = 0.5;
  double m_tick_seconds = 0.0;

  int m_level_rank = -1;
  int m_level_pc = -1;
  int m_level_sid = -1;
  int m_level_bg = -1;
  int m_level_bank = -1;
  int m_level_row = -1;
  int m_level_column = -1;

  Clk_t m_baseline_tick = 0;
  PowerStats m_baseline;
  PowerStats m_visible;
  std::size_t m_mapped_total = 0;
  std::size_t m_ignored_interface_total = 0;
  std::size_t m_unsupported_total = 0;
  std::size_t m_mapped_baseline = 0;
  std::size_t m_ignored_interface_baseline = 0;
  std::size_t m_unsupported_baseline = 0;

  static void validate_probability(const char* name, double value) {
    if (value < 0.0 || value > 1.0) {
      throw std::runtime_error(std::string("DRAMPower ") + name + " must be in [0, 1]");
    }
  }

  int level_id(const char* name) const {
    const auto& spec = *m_ctrl->m_device.m_spec;
    return spec.has_level(name) ? spec.get_level_id(name) : -1;
  }

  void cache_level_ids() {
    m_level_rank = level_id("Rank");
    m_level_pc = level_id("PseudoChannel");
    m_level_sid = level_id("Sid");
    m_level_bg = level_id("BankGroup");
    m_level_bank = level_id("Bank");
    m_level_row = level_id("Row");
    m_level_column = level_id("Column");
  }

  static std::size_t coordinate(const AddrVec_t& addr, int level) {
    return level >= 0 && level < static_cast<int>(addr.size()) && addr[level] >= 0
               ? static_cast<std::size_t>(addr[level])
               : 0;
  }

  DRAMPower::TargetCoordinate target_coordinate(const AddrVec_t& addr) const {
    return {coordinate(addr, m_level_bank),   coordinate(addr, m_level_bg),
            coordinate(addr, m_level_rank),   coordinate(addr, m_level_row),
            coordinate(addr, m_level_column), coordinate(addr, m_level_pc),
            coordinate(addr, m_level_sid),    0};
  }

  void issue_mapped(const std::string& name, const DRAMPower::TargetCoordinate& target, Clk_t timestamp,
                    bool include_interface) {
    static const std::unordered_map<std::string, DRAMPower::CmdType> mapping = {
        {"ACT", DRAMPower::CmdType::ACT},    {"PREpb", DRAMPower::CmdType::PRE},   {"PREab", DRAMPower::CmdType::PREA},
        {"RD", DRAMPower::CmdType::RD},      {"RD_S", DRAMPower::CmdType::RD},     {"WR", DRAMPower::CmdType::WR},
        {"WR_S", DRAMPower::CmdType::WR},    {"RDA", DRAMPower::CmdType::RDA},     {"RDA_S", DRAMPower::CmdType::RDA},
        {"WRA", DRAMPower::CmdType::WRA},    {"WRA_S", DRAMPower::CmdType::WRA},   {"REFpb", DRAMPower::CmdType::REFB},
        {"REFab", DRAMPower::CmdType::REFA}, {"RFMpb", DRAMPower::CmdType::RFMPB}, {"RFMab", DRAMPower::CmdType::RFMAB},
    };
    auto it = mapping.find(name);
    if (it == mapping.end()) {
      ++m_unsupported_total;
      if (m_strict_validation) {
        throw std::runtime_error("No DRAMPower mapping for Ramulator command '" + name + "'");
      }
      return;
    }
    issue_command(it->second, target, timestamp, true, include_interface);
    ++m_mapped_total;
  }

  void issue_command(DRAMPower::CmdType type, const DRAMPower::TargetCoordinate& target, Clk_t timestamp, bool core,
                     bool interface) {
    DRAMPower::Command command{static_cast<DRAMPower::timestamp_t>(timestamp), type, target};
    if (core) {
      m_model->doCoreCommand(command);
    }
    if (interface && m_include_interface) {
      m_model->doInterfaceCommand(command);
    }
  }

  void validate_model() const {
    const auto& ram = *m_ctrl->m_device.m_spec;
    auto mismatch = [this](const std::string& message) {
      if (m_strict_validation) {
        throw std::runtime_error("DRAMPower memspec mismatch: " + message);
      }
    };
    auto require_equal = [&mismatch](const char* field, std::size_t lhs, std::size_t rhs) {
      if (lhs != rhs) {
        mismatch(std::string(field) + " Ramulator=" + std::to_string(lhs) + " DRAMPower=" + std::to_string(rhs));
      }
    };
    auto require_tick = [&mismatch, this](double seconds) {
      // Ramulator stores time in integer picoseconds, while DRAMPower keeps a
      // double. Half-cycle HBM3 therefore differs by at most 0.5 ps.
      const double tolerance = std::max(0.51e-12, m_tick_seconds * 1e-6);
      if (std::abs(seconds - m_tick_seconds) > tolerance) {
        mismatch("timestamp unit Ramulator=" + std::to_string(m_tick_seconds) +
                 "s DRAMPower=" + std::to_string(seconds) + "s");
      }
    };

    if (auto* hbm = dynamic_cast<DRAMPower::HBM34*>(m_model.get())) {
      const auto& p = hbm->getMemSpec();
      if (p.memoryType != m_standard) {
        mismatch("memoryType " + p.memoryType + " vs " + m_standard);
      }
      require_equal("PseudoChannel", ram.get_level_size("PseudoChannel"), p.numberOfPseudoChannels);
      require_equal("Sid", ram.get_level_size("Sid"), p.numberOfSIDs);
      require_equal("BankGroup", ram.get_level_size("BankGroup"), p.numberOfBankGroups);
      require_equal("Bank", ram.get_level_size("Bank"), p.numberOfBanksPerGroup);
      require_equal("Row", ram.get_level_size("Row"), p.numberOfRows);
      require_equal("Column", ram.get_level_size("Column"), p.numberOfColumns);
      require_equal("width", ram.channel_width, p.bitWidth);
      require_equal("burstLength", ram.internal_prefetch_size, p.burstLength);
      require_tick(p.memTimingSpec.timeUnit);
      return;
    }
    if (auto* lp5 = dynamic_cast<DRAMPower::LPDDR5*>(m_model.get())) {
      const auto& p = lp5->getMemSpec();
      if (m_standard != "LPDDR5") {
        mismatch("memoryType LPDDR5 vs " + m_standard);
      }
      require_equal("Rank", ram.get_level_size("Rank"), p.numberOfRanks);
      require_equal("BankGroup", ram.get_level_size("BankGroup"), p.numberOfBankGroups);
      require_equal("banks total", ram.get_level_size("BankGroup") * ram.get_level_size("Bank"), p.numberOfBanks);
      require_equal("Row", ram.get_level_size("Row"), p.numberOfRows);
      require_equal("Column", ram.get_level_size("Column"), p.numberOfColumns);
      require_equal("width", ram.channel_width, p.bitWidth);
      require_equal("burstLength", ram.internal_prefetch_size, p.burstLength);
      require_tick(p.memTimingSpec.tCK);
      return;
    }
    if (auto* lp6 = dynamic_cast<DRAMPower::LPDDR6*>(m_model.get())) {
      const auto& p = lp6->getMemSpec();
      if (m_standard != "LPDDR6") {
        mismatch("memoryType LPDDR6 vs " + m_standard);
      }
      require_equal("Rank", ram.get_level_size("Rank"), p.numberOfRanks);
      require_equal("BankGroup", ram.get_level_size("BankGroup"), p.numberOfBankGroups);
      require_equal("banks total", ram.get_level_size("BankGroup") * ram.get_level_size("Bank"), p.numberOfBanks);
      require_equal("Row", ram.get_level_size("Row"), p.numberOfRows);
      require_equal("Column", ram.get_level_size("Column"), p.numberOfColumns);
      require_equal("width", ram.channel_width, p.bitWidth);
      require_equal("burstLength", 24, p.burstLength);
      require_tick(p.memTimingSpec.tCK);
      return;
    }
    mismatch("unsupported DRAMPower model class");
  }

  static PowerStats energy_stats(const DRAMPower::energy_t& core, const DRAMPower::interface_energy_info_t& interface) {
    PowerStats result;
    result.core_energy_j = core.total();
    result.interface_energy_j = interface.total();
    result.total_energy_j = result.core_energy_j + result.interface_energy_j;
    result.controller_interface_energy_j = interface.controller.dynamicEnergy + interface.controller.staticEnergy;
    result.dram_interface_energy_j = interface.dram.dynamicEnergy + interface.dram.staticEnergy;

    for (const auto& bank : core.bank_energy) {
      result.activation_energy_j += bank.E_act;
      result.precharge_energy_j += bank.E_pre + bank.E_pre_RDA + bank.E_pre_WRA;
      result.read_energy_j += bank.E_RD + bank.E_RDA;
      result.write_energy_j += bank.E_WR + bank.E_WRA;
      result.refresh_energy_j += bank.E_ref_AB + bank.E_ref_PB + bank.E_ref_SB + bank.E_ref_2B + bank.E_ref_DB;
      result.rfm_energy_j += bank.E_RFM_AB + bank.E_RFM_PB;
      result.background_energy_j += bank.E_bg_act + bank.E_bg_pre;
    }
    result.background_energy_j += core.E_bg_act_shared + core.E_PDNA + core.E_PDNP + core.E_sref + core.E_dsm;
    result.refresh_energy_j += core.E_refab;
    return result;
  }

  PowerStats cumulative_stats(Clk_t timestamp) {
    auto core = m_model->calcCoreEnergy(static_cast<DRAMPower::timestamp_t>(timestamp));
    DRAMPower::interface_energy_info_t interface;
    if (m_include_interface) {
      interface = m_model->calcInterfaceEnergy(static_cast<DRAMPower::timestamp_t>(timestamp));
    }
    return energy_stats(core, interface);
  }

  static PowerStats subtract(const PowerStats& a, const PowerStats& b) {
    PowerStats r;
    r.core_energy_j = a.core_energy_j - b.core_energy_j;
    r.interface_energy_j = a.interface_energy_j - b.interface_energy_j;
    r.total_energy_j = a.total_energy_j - b.total_energy_j;
    r.activation_energy_j = a.activation_energy_j - b.activation_energy_j;
    r.precharge_energy_j = a.precharge_energy_j - b.precharge_energy_j;
    r.read_energy_j = a.read_energy_j - b.read_energy_j;
    r.write_energy_j = a.write_energy_j - b.write_energy_j;
    r.refresh_energy_j = a.refresh_energy_j - b.refresh_energy_j;
    r.rfm_energy_j = a.rfm_energy_j - b.rfm_energy_j;
    r.background_energy_j = a.background_energy_j - b.background_energy_j;
    r.controller_interface_energy_j = a.controller_interface_energy_j - b.controller_interface_energy_j;
    r.dram_interface_energy_j = a.dram_interface_energy_j - b.dram_interface_energy_j;
    return r;
  }
};

}  // namespace Ramulator
