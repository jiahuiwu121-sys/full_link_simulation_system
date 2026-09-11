#ifndef RAMULATOR_CONTROLLER_PLUGIN_POWER_REPORTER_H
#define RAMULATOR_CONTROLLER_PLUGIN_POWER_REPORTER_H

#include <cstddef>

#include "ramulator/base/type.h"

namespace Ramulator {

struct PowerStats {
  double duration_seconds = 0.0;
  double core_energy_j = 0.0;
  double interface_energy_j = 0.0;
  double total_energy_j = 0.0;
  double average_power_w = 0.0;

  double activation_energy_j = 0.0;
  double precharge_energy_j = 0.0;
  double read_energy_j = 0.0;
  double write_energy_j = 0.0;
  double refresh_energy_j = 0.0;
  double rfm_energy_j = 0.0;
  double background_energy_j = 0.0;
  double controller_interface_energy_j = 0.0;
  double dram_interface_energy_j = 0.0;

  std::size_t mapped_commands = 0;
  std::size_t ignored_interface_commands = 0;
  std::size_t unsupported_commands = 0;
};

// Optional capability implemented by controller plugins that provide a power
// model. It deliberately is not a factory interface: the existing controller
// plugin lifecycle remains the single owner of the backend.
class IPowerReporter {
 public:
  virtual ~IPowerReporter() = default;
  virtual PowerStats power_stats(Clk_t timestamp) = 0;
  virtual void finalize_power(Clk_t timestamp) = 0;
};

}  // namespace Ramulator

#endif  // RAMULATOR_CONTROLLER_PLUGIN_POWER_REPORTER_H
