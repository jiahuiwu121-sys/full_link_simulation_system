#include "online.h"
#include "ramulator/base/config.h"
#include "ramulator/base/factory.h"
#include "ramulator/controller/controller_base.h"
#include "ramulator/dram/dram_spec.h"
#include "ramulator/frontend/i_frontend.h"
#include "ramulator/memory_system/i_memory_system.h"
#include <algorithm>
#include <cmath>
#include <cctype>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <memory>
#include <queue>
#include <set>
#include <stdexcept>

using namespace Ramulator;
namespace {
thread_local std::string last_error;
void require(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}
template<class F> int guarded(F&& f) {
    try { f(); return 1; }
    catch (const std::exception& e) { last_error = e.what(); return -1; }
    catch (...) { last_error = "unknown native exception"; return -1; }
}
struct Later {
    bool operator()(const ssr_event& a, const ssr_event& b) const {
        return a.cycle != b.cycle ? a.cycle > b.cycle : a.token > b.token;
    }
};
void json_string(std::ostream& out, const std::string& s) {
    out << '"';
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') out << '\\' << char(c);
        else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c) << std::dec;
        else out << char(c);
    }
    out << '"';
}
void stats_json(std::ostream& out, const ConfigNode& node) {
    if (node.is_map()) {
        out << '{'; bool first = true;
        for (const auto& [key, value] : node.map()) {
            if (!first) out << ','; first = false;
            json_string(out, key); out << ':'; stats_json(out, value);
        }
        out << '}';
    } else if (node.is_sequence()) {
        out << '['; bool first = true;
        for (const auto& value : node.seq()) {
            if (!first) out << ','; first = false; stats_json(out, value);
        }
        out << ']';
    } else if (node.is_scalar()) {
        const auto& s = node.scalar(); char* end = nullptr;
        const double number = std::strtod(s.c_str(), &end);
        if (s == "true" || s == "false") out << s;
        else if (!s.empty() && end == s.c_str() + s.size() && std::isfinite(number) &&
                 (std::isdigit(s.front()) || s.front() == '-')) out << s;
        else json_string(out, s);
    } else out << "null";
}
}

struct ssr_memory {
    std::unique_ptr<IFrontEnd> frontend;
    std::unique_ptr<IMemorySystem> memory;
    std::vector<ControllerBase*> controllers;
    ssr_info info{};
    uint64_t cycle = 0, submitted = 0, serviced = 0, command_count = 0;
    uint32_t limit = 0;
    bool finished = false, failed = false;
    std::string dir;
    std::map<uint64_t, uint64_t> pending;
    std::set<uint64_t> addresses;
    std::deque<ssr_event> events;
    std::priority_queue<ssr_event, std::vector<ssr_event>, Later> future;
    uint64_t sample_cycles = 1000;
    std::ofstream timeseries;

    void snapshot() {
        for (size_t i = 0; i < controllers.size(); ++i) {
            const auto depths = controllers[i]->integration_depths();
            PowerStats p; const bool enabled = controllers[i]->get_power_stats(p);
            timeseries << cycle * info.period_fs << ',' << cycle << ',' << i;
            for (auto depth : depths) timeseries << ',' << depth;
            timeseries << ',' << pending.size() << ',' << (enabled ? 1 : 0)
                << ',' << p.core_energy_j << ',' << p.interface_energy_j << ',' << p.total_energy_j
                << ',' << p.activation_energy_j << ',' << p.precharge_energy_j
                << ',' << p.read_energy_j << ',' << p.write_energy_j
                << ',' << p.refresh_energy_j << ',' << p.rfm_energy_j
                << ',' << p.background_energy_j << '\n';
        }
        require(bool(timeseries), "cannot write native metrics timeseries");
    }

    void observe(const Request& req, const ControllerBase& ctrl) {
        const auto& spec = *ctrl.m_device.m_spec;
        ssr_event e{};
        e.abi_version = SSR_ABI_VERSION; e.struct_bytes = sizeof(e);
        e.kind = 1; e.write = req.type_id == Request::Type::Write;
        e.token = req.integration_token; e.cycle = ctrl.m_clk; e.issue_cycle = e.cycle;
        e.address = req.addr >= 0 ? uint64_t(req.addr) : 0;
        e.channel = ctrl.m_channel_id; e.command = req.command;
        e.levels = req.addr_vec.size();
        require(e.levels <= 8, "unsupported address hierarchy");
        std::fill(std::begin(e.coordinates), std::end(e.coordinates), -1);
        std::copy(req.addr_vec.begin(), req.addr_vec.end(), e.coordinates);
        const auto& name = spec.command_names.at(req.command);
        require(name.size() < sizeof(e.command_name), "command name too long");
        std::memcpy(e.command_name, name.c_str(), name.size() + 1);
        events.push_back(e); ++command_count;
        if (e.token && req.command == req.final_command) {
            require(pending.count(e.token), "unknown issue token");
            e.kind = 2;
            const auto latency = e.write ? spec.write_latency : spec.read_latency;
            require(latency > 0, "standard has no data completion latency");
            e.cycle += latency;
            future.push(e);
        }
    }

    bool idle() const {
        if (!pending.empty() || !events.empty() || !future.empty()) return false;
        for (const auto* c : controllers) if (c->has_pending_demand()) return false;
        return true;
    }
};

extern "C" const char* ssr_error() { return last_error.c_str(); }
extern "C" ssr_memory* ssr_create(const char* path, uint32_t limit,
                                  uint32_t scale, const char* directory) {
    std::unique_ptr<ssr_memory> h;
    const int result = guarded([&] {
        require(path && directory && limit && scale, "invalid create arguments");
        h = std::make_unique<ssr_memory>();
        h->limit = limit; h->dir = directory;
        std::filesystem::create_directories(h->dir);
        auto config = Config::parse_config_file(path);
        if (config["integration_statistics"])
            h->sample_cycles = config["integration_statistics"]["sample_cycles"].as<uint64_t>(1000);
        require(h->sample_cycles > 0, "statistics sample_cycles must be positive");
        require(config["frontend"]["impl"].as<std::string>() == "External", "External frontend required");
        require(config["frontend"]["clock_ratio"].as<int>() == 1 &&
                config["memory_system"]["clock_ratio"].as<int>() == 1, "embedding requires clock ratios 1");
        require(config["memory_system"]["channel_mapper"]["impl"].as<std::string>() == "CacheLineInterleave",
                "embedding capacity contract requires CacheLineInterleave");
        h->frontend.reset(Factory::create_frontend(config));
        h->memory.reset(Factory::create_memory_system(config));
        h->frontend->connect_memory_system(h->memory.get());
        h->memory->connect_frontend(h->frontend.get());
        auto all = h->memory->integration_controllers();
        require(!all.empty(), "memory system has no embedding capability");
        require((all.size() & (all.size() - 1)) == 0, "channel count must be power of two");
        h->info.abi_version = SSR_ABI_VERSION; h->info.struct_bytes = sizeof(ssr_info);
        h->info.transaction_bytes = h->memory->get_tx_bytes(); h->info.channels = all.size();
        require(h->info.transaction_bytes &&
                !(h->info.transaction_bytes & (h->info.transaction_bytes - 1)),
                "CacheLineInterleave embedding requires a power-of-two transaction size");
        const auto controller_configs = config["memory_system"]["controllers"].seq();
        for (const auto& controller : controller_configs) {
            require(controller["read_buffer_size"].as<int>(32) > 0 &&
                    controller["write_buffer_size"].as<int>(32) > 0,
                    "controller read/write queues must be positive");
        }
        uint64_t channel_capacity = 0;
        for (auto* base : all) {
            auto* c = dynamic_cast<ControllerBase*>(base);
            require(c, "controller has no embedding capability");
            const auto& spec = *c->m_device.m_spec;
            require(spec.read_latency > 0 && spec.write_latency > 0 && c->get_period_ps() > 0,
                    "invalid model latency or clock");
            uint64_t capacity = spec.get_tx_bytes();
            for (int i = 1; i < spec.level_count; ++i) {
                uint64_t count = spec.organization.level_sizes.at(i);
                if (i == spec.level_count - 1) count /= spec.internal_prefetch_size;
                require(count && capacity <= UINT64_MAX / count, "invalid organization capacity");
                capacity *= count;
            }
            const uint64_t period = uint64_t(c->get_period_ps()) * 1000 * scale;
            if (h->controllers.empty()) {
                h->info.period_fs = period; channel_capacity = capacity;
                h->info.read_latency = spec.read_latency; h->info.write_latency = spec.write_latency;
            } else {
                require(capacity == channel_capacity && period == h->info.period_fs &&
                        spec.get_tx_bytes() == int(h->info.transaction_bytes) &&
                        spec.read_latency == int64_t(h->info.read_latency) &&
                        spec.write_latency == int64_t(h->info.write_latency), "heterogeneous controllers unsupported");
            }
            // Absolute DRAMPower values require the native timing timebase.
            // Scaling is interpreted as idle spacing externally, not changed memspec.
            require(scale == 1, "clock scale must be 1; use a matching slower DRAM timing and memspec");
            h->controllers.push_back(c);
            c->issue_observer = [instance = h.get()](const Request& r, const ControllerBase& ctrl) {
                instance->observe(r, ctrl);
            };
        }
        require(channel_capacity <= uint64_t(INT64_MAX) / all.size(), "capacity exceeds native signed address");
        h->info.capacity_bytes = channel_capacity * all.size();
        // A model manifest lets an offline checker inspect actual resolved rules
        // without loading the simulator or invoking its scheduling functions.
        std::ofstream model(h->dir + "/ramulator_model.json");
        model << "{\"controllers\":[";
        for (size_t channel = 0; channel < h->controllers.size(); ++channel) {
            const auto& spec = *h->controllers[channel]->m_device.m_spec;
            if (channel) model << ',';
            model << "{\"standard\":\"" << spec.standard_name << "\",\"bank_level\":"
                  << spec.get_level_id("Bank") << ",\"row_level\":" << spec.get_level_id("Row")
                  << ",\"levels\":[";
            for (int i = 0; i < spec.level_count; ++i) {
                if (i) model << ',';
                model << '"' << spec.level_names[i] << '"';
            }
            model << "],\"commands\":[";
            for (int i = 0; i < spec.command_count; ++i) {
                if (i) model << ',';
                model << '"' << spec.command_names[i] << '"';
            }
            model << "],\"organization\":[";
            for (int i = 0; i < spec.level_count; ++i) {
                if (i) model << ',';
                model << spec.organization.level_sizes[i];
            }
            model << "],\"constraints\":[";
            bool first = true;
            for (int level = 0; level < spec.level_count; ++level)
                for (int preceding = 0; preceding < spec.command_count; ++preceding)
                    for (const auto& t : spec.timing_cons[level][preceding]) {
                        if (!first) model << ',';
                        first = false;
                        model << '[' << level << ',' << preceding << ',' << t.cmd << ','
                              << t.val << ',' << t.window << ',' << (t.sibling ? "true" : "false") << ']';
                    }
            model << "]}";
        }
        model << "]}\n";
        require(bool(model), "cannot record model manifest");
        for (size_t channel = 0; channel < controller_configs.size(); ++channel) {
            const auto plugins = controller_configs[channel]["controller_plugins"];
            if (!plugins) continue;
            for (const auto& plugin : plugins.seq()) {
                if (plugin["impl"].as<std::string>() != "DRAMPower") continue;
                const auto source = std::filesystem::path(plugin["memspec_path"].as<std::string>());
                const auto target = std::filesystem::path(h->dir) /
                    ("ramulator_memspec_channel_" + std::to_string(channel) + ".json");
                if (std::filesystem::absolute(source).lexically_normal() != std::filesystem::absolute(target).lexically_normal())
                    std::filesystem::copy_file(source, target, std::filesystem::copy_options::overwrite_existing);
            }
        }
        std::ofstream copy(h->dir + "/ramulator_config.yaml");
        std::ifstream input(path); copy << input.rdbuf();
        require(bool(input) && bool(copy), "cannot record expanded configuration");
        h->timeseries.open(h->dir + "/ramulator_timeseries.csv");
        h->timeseries << std::setprecision(17)
            << "tick_fs,cycle,channel,read_queue,write_queue,priority_queue,active_queue,pending_reads,native_global_inflight,power_enabled,core_energy_j,interface_energy_j,total_energy_j,activation_energy_j,precharge_energy_j,read_energy_j,write_energy_j,refresh_energy_j,rfm_energy_j,background_energy_j\n";
        h->snapshot();
    });
    return result < 0 ? nullptr : h.release();
}
extern "C" int ssr_get_info(ssr_memory* h, ssr_info* out) {
    return guarded([&] { require(h && out, "null info argument"); *out = h->info; });
}
extern "C" int ssr_submit(ssr_memory* h, uint64_t token, uint64_t addr, uint32_t write) {
    int accepted = 0;
    int status = guarded([&] {
        require(h && !h->finished && !h->failed, "invalid native lifecycle");
        require(token && write <= 1 && !h->pending.count(token), "invalid or duplicate token");
        require(addr % h->info.transaction_bytes == 0 && addr < h->info.capacity_bytes,
                "unaligned or out-of-range native transaction");
        if (h->pending.size() >= h->limit || h->addresses.count(addr)) return;
        Request req(Addr_t(addr), write ? Request::Type::Write : Request::Type::Read, 0, {});
        req.integration_token = token; req.size_bytes = h->info.transaction_bytes;
        if (h->memory->send(req)) {
            h->pending.emplace(token, addr); h->addresses.insert(addr); ++h->submitted; accepted = 1;
        }
    });
    return status < 0 ? status : accepted;
}
extern "C" int ssr_step(ssr_memory* h) {
    return guarded([&] {
        require(h && !h->finished && !h->failed, "invalid native lifecycle");
        require(h->events.empty(), "poll all events before advancing");
        try {
            h->memory->tick(); ++h->cycle;
            for (auto* c : h->controllers) require(uint64_t(c->m_clk) == h->cycle, "clock drift");
            while (!h->future.empty() && h->future.top().cycle <= h->cycle) {
                auto e = h->future.top(); h->future.pop(); h->events.push_back(e);
            }
            if (h->cycle % h->sample_cycles == 0) h->snapshot();
        } catch (...) { h->failed = true; throw; }
    });
}
extern "C" int ssr_poll_event(ssr_memory* h, ssr_event* out) {
    int got = 0;
    const int status = guarded([&] {
        require(h && out && !h->failed, "invalid event argument/lifecycle");
        if (h->events.empty()) return;
        *out = h->events.front(); h->events.pop_front(); got = 1;
        if (out->kind == 2) {
            auto it = h->pending.find(out->token); require(it != h->pending.end(), "duplicate completion");
            h->addresses.erase(it->second); h->pending.erase(it); ++h->serviced;
        }
    });
    return status < 0 ? status : got;
}
extern "C" int ssr_is_idle(ssr_memory* h) {
    if (!h || h->failed) { last_error = "invalid idle argument/lifecycle"; return -1; }
    return h->idle();
}
extern "C" int ssr_finish(ssr_memory* h) {
    return guarded([&] {
        require(h && !h->finished && !h->failed && h->idle(), "finish requires fully drained live instance");
        h->memory->finalize(); h->frontend->finalize();
        h->memory->update_stats_recursive();
        h->snapshot(); h->timeseries.flush();
        std::ofstream queues(h->dir + "/ramulator_queue_metrics.json");
        queues << "{\"sample_cycles\":" << h->sample_cycles
               << ",\"measurement\":\"exact pre-service cycle samples\",\"cycles\":" << h->cycle << ",\"channels\":[";
        const char* names[] = {"read_queue", "write_queue", "priority_queue", "active_queue", "pending_reads"};
        for (size_t channel = 0; channel < h->controllers.size(); ++channel) {
            if (channel) queues << ',';
            queues << "{\"channel\":" << channel << ",\"queues\":{";
            for (size_t i = 0; i < 5; ++i) {
                if (i) queues << ',';
                const auto& q = h->controllers[channel]->integration_queues[i];
                queues << '"' << names[i] << "\":{\"depth_cycle_sum\":" << q.sum
                    << ",\"peak\":" << q.peak << ",\"nonempty_cycles\":" << q.nonempty_cycles << '}';
            }
            queues << "}}";
        }
        queues << "]}\n";
        std::ofstream stats(h->dir + "/ramulator_stats.yaml"); h->memory->print_stats(stats);
        // Same registered native statistics, names and units, without adding a
        // Python YAML dependency or reimplementing the native counter formulas.
        std::ofstream native_json(h->dir + "/ramulator_stats.json");
        native_json << "{\"memory_system\":"; stats_json(native_json, h->memory->collect_stats()); native_json << "}\n";
        std::ofstream power(h->dir + "/dram_power.json");
        power << std::setprecision(17) << "{\"passed\":true,\"timebase\":\"native\",\"duration_seconds\":"
              << h->cycle * h->info.period_fs * 1e-15 << ",\"channels\":[";
        double core = 0, interface = 0, total = 0;
        for (size_t i = 0; i < h->controllers.size(); ++i) {
            PowerStats p; const bool enabled = h->controllers[i]->get_power_stats(p);
            require(!enabled || p.unsupported_commands == 0, "unsupported power commands");
            core += p.core_energy_j; interface += p.interface_energy_j; total += p.total_energy_j;
            if (i) power << ',';
            power << "{\"channel\":" << i << ",\"enabled\":" << (enabled ? "true" : "false")
              << ",\"duration_seconds\":" << p.duration_seconds << ",\"core_energy_j\":" << p.core_energy_j
              << ",\"interface_energy_j\":" << p.interface_energy_j << ",\"total_energy_j\":" << p.total_energy_j
              << ",\"activation_energy_j\":" << p.activation_energy_j << ",\"precharge_energy_j\":" << p.precharge_energy_j
              << ",\"read_energy_j\":" << p.read_energy_j << ",\"write_energy_j\":" << p.write_energy_j
              << ",\"refresh_energy_j\":" << p.refresh_energy_j << ",\"rfm_energy_j\":" << p.rfm_energy_j
              << ",\"background_energy_j\":" << p.background_energy_j
              << ",\"controller_interface_energy_j\":" << p.controller_interface_energy_j
              << ",\"dram_interface_energy_j\":" << p.dram_interface_energy_j
              << ",\"mapped_commands\":" << p.mapped_commands << ",\"unsupported_commands\":" << p.unsupported_commands << '}';
        }
        power << "],\"core_energy_j\":" << core << ",\"interface_energy_j\":" << interface
              << ",\"total_energy_j\":" << total << ",\"average_power_w\":"
              << (h->cycle ? total / (h->cycle * h->info.period_fs * 1e-15) : 0)
              << ",\"absolute_accuracy_validated\":false,\"scope\":\"DRAM estimate; excludes XPU/AXI/UCIe/controller logic\"}\n";
        std::ofstream summary(h->dir + "/ramulator_native_summary.json");
        summary << "{\"passed\":true,\"drained\":true,\"submitted\":" << h->submitted
                << ",\"serviced\":" << h->serviced << ",\"commands\":" << h->command_count
                << ",\"cycles\":" << h->cycle << ",\"period_fs\":" << h->info.period_fs
                << ",\"capacity_bytes\":" << h->info.capacity_bytes
                << ",\"transaction_bytes\":" << h->info.transaction_bytes
                << ",\"read_latency\":" << h->info.read_latency << ",\"write_latency\":" << h->info.write_latency << "}\n";
        require(bool(stats) && bool(native_json) && bool(power) && bool(summary) && bool(queues), "cannot write native reports");
        h->finished = true;
    });
}
extern "C" void ssr_destroy(ssr_memory* h) { delete h; }
