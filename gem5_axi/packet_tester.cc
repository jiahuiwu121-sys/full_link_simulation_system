#include "packet_tester.hh"
#include "sim/sim_exit.hh"
#include "base/logging.hh"
#include <algorithm>
#include <iomanip>

namespace gem5 {
AxiPacketTester::AxiPacketTester(const AxiPacketTesterParams& p)
    : SimObject(p), port(name() + ".port", *this), base(p.base),
      requestor(p.system->getRequestorId(this)), hold(p.response_hold), directory(p.trace_dir),
      issueEvent([this] { pump(); }, name() + ".issue"),
      retryEvent([this] { retryResponse(); }, name() + ".respRetry"),
      bandwidthMode(p.traffic_mode == "bandwidth"),
      trafficInterval(p.traffic_issue_interval),
      trafficWarmup(p.traffic_warmup_requests), trafficMeasure(p.traffic_measure_requests),
      trafficCooldown(p.traffic_cooldown_requests),
      trafficTotal(trafficWarmup + trafficMeasure + trafficCooldown),
      trafficWorkingSet(p.traffic_working_set), trafficSize(p.traffic_request_size),
      trafficWritePercent(p.traffic_write_percent), trafficMaxInflight(p.traffic_max_inflight),
      trafficOfferedLoadPercent(p.traffic_offered_load_percent),
      golden(std::max<uint64_t>(8192, p.traffic_working_set), 0),
      lifecycle(directory + "/packet_lifecycle.csv") {
    fatal_if(p.traffic_mode != "validation" && p.traffic_mode != "bandwidth",
             "unknown packet tester traffic mode");
    if (bandwidthMode) {
        fatal_if(!trafficWarmup || !trafficMeasure || !trafficCooldown || !trafficSize ||
                 !trafficWorkingSet || !trafficMaxInflight || trafficSize > 4096 ||
                 trafficWorkingSet % trafficSize || trafficWorkingSet / trafficSize <= trafficMaxInflight,
                 "invalid bandwidth traffic configuration");
    }
    fatal_if(!lifecycle, "cannot open packet lifecycle");
    lifecycle << "serial,command,address,bytes,first_attempt_tick,accepted_tick,response_tick,error\n";
}
Port& AxiPacketTester::getPort(const std::string& n, PortID idx) {
    if (n == "port") return port;
    return SimObject::getPort(n, idx);
}
void AxiPacketTester::startup() {
    if (!bandwidthMode) nextStage();
    nextTrafficIssue = curTick() + 1000000;
    schedule(issueEvent, nextTrafficIssue);
}
void AxiPacketTester::add(bool wr, unsigned off, unsigned size, unsigned seed, bool masked, bool error) {
    auto req = std::make_shared<Request>(base + off, size, Request::UNCACHEABLE, requestor);
    req->setStreamId(7); req->setSubstreamId(serial + 100);
    std::vector<bool> enables(size, true);
    if (masked) for (unsigned i = 0; i < size; ++i) enables[i] = i % 3 != 1;
    auto* pkt = new Packet(req, wr ? MemCmd::WriteReq : MemCmd::ReadReq);
    pkt->allocate();
    std::fill(pkt->getPtr<uint8_t>(), pkt->getPtr<uint8_t>() + size, 0xa5);
    std::vector<uint8_t> expected(size, 0xa5);
    if (wr) {
        for (unsigned i = 0; i < size; ++i) {
            pkt->getPtr<uint8_t>()[i] = (seed + i * 37) & 255;
            if (!error && enables[i]) golden.at(off + i) = pkt->getPtr<uint8_t>()[i];
        }
    } else if (!error) {
        for (unsigned i = 0; i < size; ++i) if (enables[i]) expected[i] = golden.at(off + i);
    }
    // Exercise non-zero timing annotations through the existing gem5 bridge.
    pkt->headerDelay = bandwidthMode ? 0 : 250000;
    pkt->payloadDelay = bandwidthMode ? 0 : (wr ? 500000 : 0);
    req->setByteEnable(enables);
    ops.emplace(pkt, Op{pkt, expected, error, wr, serial++});
    queue.push_back(pkt);
}
void AxiPacketTester::addTraffic() {
    const uint64_t index = trafficGenerated;
    const uint64_t locations = trafficWorkingSet / trafficSize;
    const unsigned offset = (index % locations) * trafficSize;
    const bool write = ((index * 37 + 17) % 100) < trafficWritePercent;
    add(write, offset, trafficSize, unsigned((index * 131 + 29) & 255));
    ++trafficGenerated;
}
void AxiPacketTester::schedulePump(Tick when) {
    when = std::max(when, curTick() + 1);
    if (!issueEvent.scheduled()) schedule(issueEvent, when);
}
void AxiPacketTester::finishTraffic() {
    fatal_if(done != trafficTotal || trafficGenerated != trafficTotal || inflight || !queue.empty(),
             "bandwidth traffic finished before drain");
    fatal_if(!warmupEndTick || !measurementEndTick || measurementEndTick <= warmupEndTick,
             "invalid bandwidth measurement window");
    const Tick measurementStart = warmupEndTick + 1;
    std::ofstream profile(directory + "/traffic_profile.json");
    profile << std::setprecision(17)
            << "{\"schema\":\"storagestacked.traffic.v1\",\"passed\":true,\"mode\":\"bandwidth\""
            << ",\"requests\":" << trafficTotal << ",\"responses\":" << done
            << ",\"warmup_requests\":" << trafficWarmup
            << ",\"measurement_requests\":" << trafficMeasure
            << ",\"cooldown_requests\":" << trafficCooldown
            << ",\"request_size_bytes\":" << trafficSize
            << ",\"working_set_bytes\":" << trafficWorkingSet
            << ",\"substream_base\":100"
            << ",\"write_percent\":" << trafficWritePercent
            << ",\"max_inflight\":" << trafficMaxInflight
            << ",\"issue_interval_fs\":" << trafficInterval
            << ",\"offered_load_percent\":" << trafficOfferedLoadPercent
            << ",\"first_accepted_tick_fs\":" << firstAcceptedTick
            << ",\"measurement_start_tick_fs\":" << measurementStart
            << ",\"measurement_end_tick_fs\":" << measurementEndTick
            << ",\"request_retries\":" << reqRetries << "}\n";
    profile.close();
    std::ofstream summary(directory + "/tester_summary.json");
    summary << "{\"passed\":true,\"mode\":\"bandwidth\",\"requests\":" << trafficTotal
            << ",\"responses\":" << done << ",\"request_retries\":" << reqRetries
            << ",\"response_retries\":" << respRetries << ",\"finish_tick\":" << curTick() << "}\n";
    lifecycle.flush();
    exitSimLoop("AXI bandwidth traffic completed", 0);
}
void AxiPacketTester::nextStage() {
    ++stage;
    if (stage == 1) {
        add(true, 0, 64, 11);
        add(true, 128, 2080, 29); // aligned full-width bursts, high data lanes
        add(true, 3003, 19, 71); // unaligned, legal narrow bursts
        add(true, 4088, 32, 91); // crosses 4KiB
        add(true, 5001, 257, 13); // byte-sized: 256-beat limit plus one beat
        add(true, 6016, 96, 123);
    } else if (stage == 2) {
        add(true, 3, 17, 217, true);
        add(true, 4089, 23, 201, true);
        add(true, 6016, 96, 198, true); // masked full-width writes
        add(true, 12288, 8, 1, false, true); // DECERR in bridge routing range
    } else if (stage == 3) {
        add(false, 0, 64, 0);
        add(false, 128, 2080, 0);
        add(false, 3003, 19, 0);
        add(false, 4088, 32, 0);
        add(false, 5001, 257, 0);
        add(false, 6016, 96, 0, true);
        add(false, 12288, 8, 0, false, true);
    } else {
        std::ofstream f(directory + "/tester_summary.json");
        f << "{\"passed\":true,\"requests\":" << serial << ",\"responses\":" << done
          << ",\"request_retries\":" << reqRetries << ",\"response_retries\":"
          << respRetries << ",\"finish_tick\":" << curTick() << "}\n";
        f.close(); lifecycle.flush();
        exitSimLoop("AXI packet/data/retry tests passed", 0);
    }
}
void AxiPacketTester::pump() {
    if (blocked) return;
    if (bandwidthMode) {
        while (trafficGenerated < trafficTotal && inflight + queue.size() < trafficMaxInflight &&
               (!trafficInterval || curTick() >= nextTrafficIssue)) {
            addTraffic();
            if (trafficInterval) {
                nextTrafficIssue = curTick() + trafficInterval;
                break;
            }
        }
    }
    while (!queue.empty()) {
        auto* pkt = queue.front(); auto& op = ops.at(pkt);
        if (!op.attempt) op.attempt = curTick();
        if (!port.sendTimingReq(pkt)) { blocked = true; return; }
        op.accepted = curTick();
        if (!firstAcceptedTick) firstAcceptedTick = curTick();
        ++inflight; queue.pop_front();
    }
    if (bandwidthMode && trafficGenerated < trafficTotal && !blocked &&
        inflight + queue.size() < trafficMaxInflight && trafficInterval)
        schedulePump(nextTrafficIssue);
}
bool AxiPacketTester::response(PacketPtr pkt) {
    if (hold && !delayed.count(pkt)) {
        delayed.insert(pkt); waitingResponse = pkt; ++respRetries;
        schedule(retryEvent, curTick() + hold);
        return false;
    }
    auto it = ops.find(pkt);
    fatal_if(it == ops.end(), "unknown/duplicate response");
    auto& op = it->second;
    fatal_if(pkt->isError() != op.error, "incorrect AXI error propagation");
    if (!op.error && pkt->isRead()) {
        for (unsigned i = 0; i < pkt->getSize(); ++i)
            fatal_if(pkt->getConstPtr<uint8_t>()[i] != op.expected[i],
                     "read mismatch at %#x byte %u: got %u expected %u", pkt->getAddr(), i,
                     pkt->getConstPtr<uint8_t>()[i], op.expected[i]);
    }
    lifecycle << op.serial << ',' << (op.write ? 'W' : 'R') << ',' << pkt->getAddr()
              << ',' << pkt->getSize() << ',' << op.attempt << ',' << op.accepted << ','
              << curTick() << ',' << pkt->isError() << '\n';
    lifecycle.flush();
    const uint64_t completedSerial = op.serial;
    delayed.erase(pkt); ops.erase(it); delete pkt;
    ++done; --inflight;
    if (bandwidthMode) {
        if (completedSerial < trafficWarmup)
            warmupEndTick = std::max<uint64_t>(warmupEndTick, curTick());
        else if (completedSerial < trafficWarmup + trafficMeasure)
            measurementEndTick = std::max<uint64_t>(measurementEndTick, curTick());
        if (done == trafficTotal) finishTraffic();
        else if (!blocked) {
            if (!trafficInterval) pump();
            else schedulePump(std::max(curTick() + 1, nextTrafficIssue));
        }
        return true;
    }
    if (!inflight && queue.empty()) {
        nextStage();
        if (!queue.empty()) schedule(issueEvent, curTick() + 1);
    }
    return true;
}
void AxiPacketTester::retryResponse() {
    panic_if(!waitingResponse, "response retry without blocked response");
    waitingResponse = nullptr;
    port.sendRetryResp();
}
}
