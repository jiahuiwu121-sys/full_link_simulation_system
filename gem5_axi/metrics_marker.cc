#include "metrics_marker.hh"
#include "mem/packet_access.hh"
#include "base/logging.hh"
#include "sim/cur_tick.hh"
namespace gem5 {
MetricsMarker::MetricsMarker(const Params& p)
    : BasicPioDevice(p, 4096), log(p.trace_dir + "/application_markers.csv") {
    fatal_if(!log, "Cannot open application marker statistics");
    log << "tick_fs,marker\n"; log.flush();
}
Tick MetricsMarker::read(PacketPtr pkt) {
    fatal_if(pkt->getAddr() != pioAddr || pkt->getSize() != 4, "Invalid metrics marker access");
    pkt->setLE<uint32_t>(last); pkt->makeAtomicResponse(); return pioDelay;
}
Tick MetricsMarker::write(PacketPtr pkt) {
    fatal_if(pkt->getAddr() != pioAddr || pkt->getSize() != 4, "Invalid metrics marker access");
    last = pkt->getLE<uint32_t>();
    log << curTick() << ',' << last << '\n'; log.flush();
    fatal_if(!log, "Cannot record application marker");
    pkt->makeAtomicResponse(); return pioDelay;
}
}
