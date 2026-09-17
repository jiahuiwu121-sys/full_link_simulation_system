#pragma once
#include <systemc>
#include "simple_mem_if.h"
#include "ramulator2/integration/online.h"
#include "target_backing_store.hh"
#include <deque>
#include <fstream>
#include <map>
#include <memory>

class RamulatorBackend : public sc_core::sc_module {
  public:
    sc_core::sc_fifo_in<SimpleMemRequest> request{"request"};
    sc_core::sc_fifo_out<SimpleMemResponse> response{"response"};
    uint64_t completed = 0, error_responses = 0;
    SC_HAS_PROCESS(RamulatorBackend);
    RamulatorBackend(sc_core::sc_module_name, uint64_t base, uint64_t size,
                     unsigned slots, unsigned children, unsigned hold,
                     const std::string& config, const std::string& dir);
    ~RamulatorBackend();
    void finish();
  private:
    struct Descriptor {
        uint64_t token = 0, address = 0;
        unsigned offset = 0, bytes = 0;
        bool submitted = false, complete = false;
    };
    struct Burst {
        uint64_t serial = 0, ready = 0;
        SimpleMemRequest req;
        SimpleMemResponse rsp;
        std::vector<uint8_t> data, mask;
        std::vector<Descriptor> descriptors;
        unsigned length = 0, remaining = 0;
    };
    struct Child { std::shared_ptr<Burst> burst; unsigned index; };
    uint64_t base, size, period, cycle = 0, nextBurst = 1, nextToken = 1;
    uint64_t submitted = 0, services = 0, submitStalls = 0, hazardStalls = 0, responseStalls = 0;
    unsigned slots, childLimit, hold;
    ssr_info info{};
    ssr_memory* native = nullptr;
    TargetBackingStore backing;
    std::string dir;
    std::ofstream log, commands;
    std::deque<std::shared_ptr<Burst>> bursts;
    std::map<uint64_t, Child> active;
    std::map<uint64_t, std::deque<uint64_t>> hazards;
    void run();
    void accept(SimpleMemRequest);
    void submit();
    void process(const ssr_event&);
    void event(const char*, const Burst&, unsigned offset = 0, unsigned bytes = 0,
               uint64_t token = 0, uint64_t issue = 0, uint64_t complete = 0,
               const uint8_t* data = nullptr, const uint8_t* mask = nullptr);
    int checked(int);
};
