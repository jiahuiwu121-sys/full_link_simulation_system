#pragma once
#include "dev/io_device.hh"
#include "params/MetricsMarker.hh"
#include <fstream>
namespace gem5 {
class MetricsMarker : public BasicPioDevice {
  public:
    using Params = MetricsMarkerParams;
    explicit MetricsMarker(const Params&);
    Tick read(PacketPtr) override;
    Tick write(PacketPtr) override;
  private:
    std::ofstream log;
    uint32_t last = 0;
};
}
