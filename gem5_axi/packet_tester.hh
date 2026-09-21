#pragma once
#include "sim/sim_object.hh"
#include "sim/system.hh"
#include "mem/port.hh"
#include "params/AxiPacketTester.hh"
#include <deque>
#include <fstream>
#include <map>
#include <set>

namespace gem5 {
class AxiPacketTester : public SimObject {
  public:
    explicit AxiPacketTester(const AxiPacketTesterParams&);
    Port& getPort(const std::string&, PortID idx = InvalidPortID) override;
    void startup() override;
  private:
    class TesterPort : public RequestPort {
      public:
        AxiPacketTester& owner;
        TesterPort(const std::string& n, AxiPacketTester& o) : RequestPort(n), owner(o) {}
        bool recvTimingResp(PacketPtr p) override { return owner.response(p); }
        void recvReqRetry() override { owner.reqRetries++; owner.blocked = false; owner.pump(); }
    } port;
    struct Op {
        PacketPtr packet;
        std::vector<uint8_t> expected;
        bool error, write;
        uint64_t serial;
        Tick attempt = 0, accepted = 0;
    };
    Addr base;
    RequestorID requestor;
    Tick hold;
    std::string directory;
    EventFunctionWrapper issueEvent, retryEvent;
    bool bandwidthMode = false;
    Tick trafficInterval = 0, nextTrafficIssue = 0;
    uint64_t trafficWarmup = 0, trafficMeasure = 0, trafficCooldown = 0;
    uint64_t trafficTotal = 0, trafficGenerated = 0, trafficWorkingSet = 0;
    unsigned trafficSize = 0, trafficWritePercent = 0, trafficMaxInflight = 0;
    double trafficOfferedLoadPercent = 0.0;
    std::deque<PacketPtr> queue;
    std::map<PacketPtr, Op> ops;
    std::set<PacketPtr> delayed;
    std::vector<uint8_t> golden;
    std::ofstream lifecycle;
    PacketPtr waitingResponse = nullptr;
    bool blocked = false;
    unsigned stage = 0, inflight = 0;
    uint64_t serial = 0, done = 0, reqRetries = 0, respRetries = 0;
    uint64_t warmupEndTick = 0, measurementEndTick = 0, firstAcceptedTick = 0;
    void add(bool write, unsigned offset, unsigned size, unsigned seed,
             bool masked = false, bool error = false);
    void nextStage();
    void addTraffic();
    void finishTraffic();
    void schedulePump(Tick);
    void pump();
    bool response(PacketPtr);
    void retryResponse();
};
}
