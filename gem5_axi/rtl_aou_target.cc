#include "rtl_aou_target.hh"

#ifdef SS_STORAGE_BRIDGE_RTL

#include "axi_contract.h"

#include <algorithm>
#include <stdexcept>

namespace storage_axi {
using namespace sc_core;

namespace {
template <typename Wide>
void zeroWide(Wide& value, unsigned words)
{
    for (unsigned i = 0; i < words; ++i)
        value[i] = 0;
}

template <typename Wide>
void bytesToWide(Wide& value, const uint8_t* bytes, unsigned count, unsigned words)
{
    zeroWide(value, words);
    for (unsigned i = 0; i < count; ++i)
        value[i / 4] |= uint32_t(bytes[i]) << (8 * (i % 4));
}

template <typename Wide>
void wideToBytes(const Wide& value, uint8_t* bytes, unsigned count)
{
    for (unsigned i = 0; i < count; ++i)
        bytes[i] = (value[i / 4] >> (8 * (i % 4))) & 0xff;
}

bool strobeBit(const Vstorage_bridge_top& rtl, unsigned bit)
{
#if AXI_DATA_WIDTH_CFG == 256
    return (rtl.hif_w_strb >> bit) & 1u;
#else
    return (rtl.hif_w_strb[bit / 32] >> (bit % 32)) & 1u;
#endif
}
} // anonymous namespace

RtlAouTarget::RtlAouTarget(sc_module_name name, unsigned resource_planes)
    : sc_module(name), planes(resource_planes),
      context(std::make_unique<VerilatedContext>()),
      rtl(std::make_unique<Vstorage_bridge_top>(context.get(), "rtl"))
{
    if (planes < 1 || planes > 4)
        throw std::invalid_argument("RTL target resource planes must be 1..4");
    SC_THREAD(run);
    sensitive << clk.pos();
}

RtlAouTarget::~RtlAouTarget()
{
    rtl->final();
}

bool RtlAouTarget::writeDataReady(unsigned rp) const
{
    if (rp >= planes)
        return false;
    const auto& jobs = write_jobs[rp];
    return std::any_of(jobs.begin(), jobs.end(), [](const auto& req) {
        return req.write_beats.size() < req.beats();
    });
}

bool RtlAouTarget::idle() const
{
    // A late FDI frame may contain only returned credits. Once every accepted
    // memory transaction has produced its response, such maintenance traffic
    // is not functional work and must not prevent a clean simulation finish.
    // StorageBridge and RamulatorBackend separately assert that both memory
    // FIFOs, all parents, all native children and the hazard table are empty.
    if (reply || outstanding)
        return false;
    for (unsigned rp = 0; rp < planes; ++rp)
        if (!write_jobs[rp].empty())
            return false;
    return true;
}

void RtlAouTarget::submitAssembledWrite()
{
    if (outstanding >= MaxOutstanding || mem_req.num_free() == 0)
        return;
    for (unsigned n = 0; n < planes; ++n) {
        const unsigned rp = (next_write_submit + n) % planes;
        auto& jobs = write_jobs[rp];
        if (jobs.empty() || jobs.front().write_beats.size() != jobs.front().beats())
            continue;
        if (!mem_req.nb_write(jobs.front()))
            return;
        jobs.pop_front();
        ++outstanding;
        next_write_submit = (rp + 1) % planes;
        return;
    }
}

void RtlAouTarget::prepareInputs()
{
    submitAssembledWrite();
    if (!incoming) {
        FdiFlit f;
        if (link_rx.nb_read(f)) {
            if (f.valid_bytes != 250 || f.payload.size() != 250)
                SC_REPORT_FATAL("RtlAouTarget", "FDI input must contain exactly 250 AoU bytes");
            incoming = std::move(f);
        }
    }
    if (!reply) {
        SimpleMemResponse rsp;
        if (mem_rsp.nb_read(rsp))
            reply = Reply{std::move(rsp), 0};
    }

    rtl->fdi_rx_valid = incoming.has_value();
    zeroWide(rtl->fdi_rx_data, 63);
    if (incoming)
        bytesToWide(rtl->fdi_rx_data, incoming->payload.data(), 250, 63);

    rtl->hif_rsp_valid = reply.has_value();
    rtl->hif_rsp_write = reply ? reply->rsp.write : false;
    rtl->hif_rsp_rp = reply ? reply->rsp.rp : 0;
    rtl->hif_rsp_id = reply ? reply->rsp.id : 0;
    rtl->hif_rsp_user = reply ? reply->rsp.user : 0;
    rtl->hif_rsp_status = reply ? reply->rsp.resp : 0;
    rtl->hif_rsp_last = false;
    zeroWide(rtl->hif_rsp_data, AXI_DATA_WIDTH_CFG / 32);
    if (reply && !reply->rsp.write) {
        const auto& beat = reply->rsp.read_beats.at(reply->beat);
        rtl->hif_rsp_user = beat.user;
        rtl->hif_rsp_status = beat.resp;
        rtl->hif_rsp_last = reply->beat + 1 == reply->rsp.read_beats.size();
        bytesToWide(rtl->hif_rsp_data, beat.data.data(), AXI_DATA_BYTES,
                    AXI_DATA_WIDTH_CFG / 32);
    }
}

void RtlAouTarget::acceptCommand()
{
    SimpleMemRequest req;
    req.write = rtl->hif_cmd_write;
    req.rp = rtl->hif_cmd_rp;
    auto& a = req.address;
    a.id = rtl->hif_cmd_id;
    a.user = rtl->hif_cmd_user;
    a.addr = rtl->hif_cmd_addr;
    a.len = rtl->hif_cmd_len;
    a.size = rtl->hif_cmd_size;
    a.lock = rtl->hif_cmd_lock;
    a.prot = rtl->hif_cmd_prot;
    a.cache = rtl->hif_cmd_cache;
    a.qos = rtl->hif_cmd_qos;
    a.burst = 1;
    if (req.rp >= planes || axi_request_error(a))
        SC_REPORT_FATAL("RtlAouTarget", "invalid decoded HIF command");
    if (req.write) {
        req.write_beats.reserve(req.beats());
        write_jobs[req.rp].push_back(std::move(req));
        ++writes;
    } else {
        if (!mem_req.nb_write(req))
            SC_REPORT_FATAL("RtlAouTarget", "reserved read request FIFO rejected command");
        ++outstanding;
        ++reads;
    }
}

void RtlAouTarget::acceptWriteData()
{
    const unsigned rp = rtl->hif_w_rp;
    if (!writeDataReady(rp))
        SC_REPORT_FATAL("RtlAouTarget", "write data has no preceding write command");
    auto& jobs = write_jobs[rp];
    auto it = std::find_if(jobs.begin(), jobs.end(), [](const auto& req) {
        return req.write_beats.size() < req.beats();
    });
    SimpleMemWriteBeat beat;
    wideToBytes(rtl->hif_w_data, beat.data.data(), AXI_DATA_BYTES);
    for (unsigned i = 0; i < AXI_DATA_BYTES; ++i)
        beat.strobe[i] = strobeBit(*rtl, i) ? 0xff : 0;
    beat.user = rtl->hif_w_user;
    it->write_beats.push_back(std::move(beat));
    ++write_beats;
}

void RtlAouTarget::acceptResponseBeat()
{
    if (!reply)
        SC_REPORT_FATAL("RtlAouTarget", "RTL accepted an absent memory response");
    if (!reply->rsp.write)
        ++read_beats;
    if (reply->rsp.write || ++reply->beat == reply->rsp.read_beats.size()) {
        if (!outstanding)
            SC_REPORT_FATAL("RtlAouTarget", "response underflow");
        --outstanding;
        reply.reset();
    }
}

void RtlAouTarget::run()
{
    rtl->clk = 0;
    rtl->rst_n = 0;
    rtl->fdi_rx_valid = 0;
    rtl->fdi_tx_ready = 0;
    rtl->hif_cmd_ready = 0;
    rtl->hif_w_ready = 0;
    rtl->hif_rsp_valid = 0;
    rtl->eval();
    while (!rst_n.read()) {
        rtl->clk = 1; rtl->eval();
        rtl->clk = 0; rtl->eval();
        wait();
    }
    rtl->rst_n = 1;

    while (true) {
        prepareInputs();
        rtl->clk = 0;
        rtl->hif_cmd_ready = 0;
        rtl->hif_w_ready = 0;
        rtl->fdi_tx_ready = link_tx.num_free() != 0;
        rtl->eval();

        const unsigned cmd_rp = rtl->hif_cmd_rp;
        rtl->hif_cmd_ready = rtl->hif_cmd_write
            ? (cmd_rp < planes && write_jobs[cmd_rp].size() < RequestSlots)
            : (outstanding < MaxOutstanding && mem_req.num_free() != 0);
        rtl->hif_w_ready = writeDataReady(rtl->hif_w_rp);
        rtl->eval();

        const bool take_fdi = rtl->fdi_rx_valid && rtl->fdi_rx_ready;
        const bool put_fdi = rtl->fdi_tx_valid && rtl->fdi_tx_ready;
        const bool take_cmd = rtl->hif_cmd_valid && rtl->hif_cmd_ready;
        const bool take_w = rtl->hif_w_valid && rtl->hif_w_ready;
        const bool take_rsp = rtl->hif_rsp_valid && rtl->hif_rsp_ready;
        std::array<uint8_t, 250> tx_bytes{};
        if (put_fdi)
            wideToBytes(rtl->fdi_tx_data, tx_bytes.data(), tx_bytes.size());

        rtl->clk = 1;
        rtl->eval();
        if (rtl->protocol_error)
            SC_REPORT_FATAL("RtlAouTarget", "RTL protocol_error asserted");
        if (take_fdi) { incoming.reset(); ++rx_flits; }
        if (take_cmd) acceptCommand();
        if (take_w) acceptWriteData();
        if (take_rsp) acceptResponseBeat();
        if (put_fdi) {
            FdiFlit f;
            f.payload.assign(tx_bytes.begin(), tx_bytes.end());
            f.valid_bytes = tx_bytes.size();
            f.transaction_id = tx_id++;
            f.vc = 0;
            f.kind = BusinessKind::Response;
            f.transaction_start = f.fdi_time = sc_time_stamp();
            if (!link_tx.nb_write(f))
                SC_REPORT_FATAL("RtlAouTarget", "reserved FDI TX FIFO rejected frame");
            ++tx_flits;
        }
        rtl->clk = 0;
        rtl->eval();
        if (!rst_n.read())
            SC_REPORT_FATAL("RtlAouTarget", "hot reset requires complete link reconstruction");
        wait();
    }
}

} // namespace storage_axi
#endif
