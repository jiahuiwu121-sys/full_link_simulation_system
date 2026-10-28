#include "rtl_aou_target.hh"
#ifdef SS_STORAGE_BRIDGE_RTL
#include "axi_contract.h"
#include "aou_stream_decoder.h"
#include "aou_wire.h"
#include "credit_manager.h"
#include "sim/cur_tick.hh"
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <numeric>
#include <sstream>
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
#if AXI_DATA_WIDTH_CFG <= 512
    return (rtl.hif_w_strb >> bit) & 1u;
#else
    return (rtl.hif_w_strb[bit / 32] >> (bit % 32)) & 1u;
#endif
}
} // anonymous namespace


RtlAouTarget::RtlAouTarget(sc_module_name name,const gem5::AxiDemoParams& p,const std::string& dir)
    : sc_module(name),planes(p.planes),period_fs(p.period),directory(dir),
      context(std::make_unique<VerilatedContext>()),
      rtl(std::make_unique<Vstorage_bridge_top>(context.get(),"rtl")),
      events(dir+"/storage_bridge_events.csv")
{
    rtl->clk=0;rtl->rst_n=0;rtl->fdi_rx_valid=0;rtl->fdi_tx_ready=0;
    rtl->hif_cmd_ready=0;rtl->hif_w_ready=0;rtl->hif_rsp_valid=0;rtl->eval();
    const std::pair<unsigned,unsigned> checks[]={
        {rtl->config_axi_width,AXI_DATA_WIDTH_CFG},{rtl->config_resource_planes,p.planes},
        {rtl->config_request_slots,p.storage_bridge_request_slots},
        {rtl->config_max_outstanding,p.storage_bridge_max_outstanding},
        {rtl->config_wdata_granules,p.storage_bridge_wdata_granules},
        {rtl->config_frame_fifo_depth,p.storage_bridge_frame_fifo_depth},
        {rtl->config_tx_flush_cycles,p.storage_bridge_tx_flush_cycles}};
    for(const auto& values:checks) if(values.first!=values.second)
        throw std::invalid_argument("StorageBridge RTL compiled parameters differ from runtime configuration; rebuild with env/build.sh");
    if(!events) throw std::runtime_error("cannot open StorageBridge event log");
    events<<"tick_fs,event,rp,id,beat,latency_fs,bytes\n";
    if(p.storage_bridge_trace) {
        context->traceEverOn(true);trace=std::make_unique<VerilatedVcdC>();
        rtl->trace(trace.get(),4);trace->set_time_unit("1fs");trace->set_time_resolution("1fs");
        trace->open((dir+"/storage_bridge_rtl.vcd").c_str());
    }
    SC_THREAD(run);
    sensitive<<clk;
}
RtlAouTarget::~RtlAouTarget() { rtl->final();if(trace) trace->close(); }
void RtlAouTarget::evaluate()
{
    context->time(sc_time_stamp().value());rtl->eval();
    if(rtl->protocol_error) {
        std::ostringstream message;message<<"RTL protocol_error, cause mask=0x"<<std::hex<<rtl->error_code
            <<" (rx=1 decode=2 credit=4 transaction=8 tx=16 type=32)";
        SC_REPORT_FATAL("RtlAouTarget",message.str().c_str());
    }
}
void RtlAouTarget::dumpTrace() { if(trace) trace->dump(static_cast<uint64_t>(sc_time_stamp().value())); }
bool RtlAouTarget::maintenanceOnly(const FdiFlit& f)
{
    if(f.valid_bytes!=250 || f.payload.size()!=250) return false;
    try {
        AouWireFlit bytes{};std::copy(f.payload.begin(),f.payload.end(),bytes.begin());
        const auto frame=deserialize_aou(bytes);
        if(frame.fdid!=0) return false;
        AouStreamDecoder decoder;const auto result=decoder.consume(frame);
        if(decoder.carry_active()) return false;
        for(const auto& message:result.messages) {
            CreditMatrix grants{};
            if(!decode_crdt_grant_message(message,4,grants)) return false;
        }
        return true;
    } catch(const std::exception&) { return false; }
}
bool RtlAouTarget::idle() const
{
    return rtl->business_idle && !reply && !assembly &&
        (!incoming || maintenanceOnly(*incoming)) &&
        std::all_of(observations.begin(),observations.end(),[](const auto& x){return !x.active;});
}
void RtlAouTarget::prepareInputs()
{
    if(!incoming) {
        FdiFlit f;
        if(link_rx.nb_read(f)) {
            if(f.valid_bytes!=250 || f.payload.size()!=250)
                SC_REPORT_FATAL("RtlAouTarget","FDI input must contain exactly 250 bytes");
            incoming=std::move(f);
        }
    }
    if(!reply) {
        SimpleMemResponse r;
        if(mem_rsp.nb_read(r)) {
            if(r.rp>=planes || r.id>1023 || (!r.write && r.read_beats.empty()) ||
                (r.write && !r.read_beats.empty()))
                SC_REPORT_FATAL("RtlAouTarget","malformed backend response representation");
            reply=Reply{std::move(r),0};
        }
    }
    rtl->fdi_rx_valid=incoming.has_value();
    zeroWide(rtl->fdi_rx_data,63);
    if(incoming) bytesToWide(rtl->fdi_rx_data,incoming->payload.data(),250,63);
    rtl->hif_rsp_valid=reply.has_value();rtl->hif_rsp_write=reply?reply->rsp.write:0;
    rtl->hif_rsp_rp=reply?reply->rsp.rp:0;rtl->hif_rsp_id=reply?reply->rsp.id:0;
    rtl->hif_rsp_user=reply?reply->rsp.user:0;rtl->hif_rsp_status=reply?reply->rsp.resp:0;
    rtl->hif_rsp_last=0;zeroWide(rtl->hif_rsp_data,AXI_DATA_WIDTH_CFG/32);
    if(reply && !reply->rsp.write) {
        const auto& b=reply->rsp.read_beats.at(reply->beat);
        rtl->hif_rsp_user=b.user;rtl->hif_rsp_status=b.resp;
        rtl->hif_rsp_last=reply->beat+1==reply->rsp.read_beats.size();
        bytesToWide(rtl->hif_rsp_data,b.data.data(),AXI_DATA_BYTES,AXI_DATA_WIDTH_CFG/32);
    }
}
SimpleMemRequest RtlAouTarget::sampleCommand() const
{
    SimpleMemRequest r;r.write=rtl->hif_cmd_write;r.rp=rtl->hif_cmd_rp;
    auto& a=r.address;a.id=rtl->hif_cmd_id;a.user=rtl->hif_cmd_user;a.addr=rtl->hif_cmd_addr;
    a.len=rtl->hif_cmd_len;a.size=rtl->hif_cmd_size;a.lock=rtl->hif_cmd_lock;
    a.prot=rtl->hif_cmd_prot;a.cache=rtl->hif_cmd_cache;a.qos=rtl->hif_cmd_qos;a.burst=1;
    if(r.rp>=planes || axi_request_error(a)) SC_REPORT_FATAL("RtlAouTarget","invalid HIF command");
    return r;
}
SimpleMemWriteBeat RtlAouTarget::sampleWriteData() const
{
    SimpleMemWriteBeat b;wideToBytes(rtl->hif_w_data,b.data.data(),AXI_DATA_BYTES);
    for(unsigned i=0;i<AXI_DATA_BYTES;i++) b.strobe[i]=strobeBit(*rtl,i)?0xff:0;
    b.user=rtl->hif_w_user;return b;
}
void RtlAouTarget::run()
{
    bool started=false;
    while(true) {
        wait();
        if(!rst_n.read()) {
            if(started) SC_REPORT_FATAL("RtlAouTarget","hot reset requires complete link reconstruction");
            rtl->rst_n=0;rtl->clk=clk.read();evaluate();dumpTrace();continue;
        }
        started=true;rtl->rst_n=1;
        if(!clk.read()) {rtl->clk=0;evaluate();dumpTrace();continue;}
        rtl->clk=0;prepareInputs();
        rtl->hif_cmd_ready=0;rtl->hif_w_ready=0;rtl->fdi_tx_ready=link_tx.num_free()!=0;evaluate();
        rtl->hif_cmd_ready=!assembly && (rtl->hif_cmd_write || mem_req.num_free()!=0);
        rtl->hif_w_ready=assembly &&
            (assembly->write_beats.size()+1<assembly->beats() || mem_req.num_free()!=0);
        evaluate();
        const bool rx=rtl->fdi_rx_valid&&rtl->fdi_rx_ready;
        const bool tx=rtl->fdi_tx_valid&&rtl->fdi_tx_ready;
        const bool cmd=rtl->hif_cmd_valid&&rtl->hif_cmd_ready;
        const bool w=rtl->hif_w_valid&&rtl->hif_w_ready;
        const bool rsp=rtl->hif_rsp_valid&&rtl->hif_rsp_ready;
        const bool last=rtl->hif_w_last;
        const auto command=cmd?std::optional<SimpleMemRequest>(sampleCommand()):std::nullopt;
        const auto beat=w?std::optional<SimpleMemWriteBeat>(sampleWriteData()):std::nullopt;
        const unsigned w_rp=rtl->hif_w_rp;
        const uint64_t command_latency=uint64_t(rtl->hif_cmd_latency_cycles)*period_fs;
        const uint64_t now=sc_time_stamp().value();
        std::array<uint8_t,250> bytes{};
        if(tx) wideToBytes(rtl->fdi_tx_data,bytes.data(),250);
        if(rtl->response_known) {
            auto& x=observations.at(rtl->response_tag);
            if(!x.active) x={true,now,unsigned(rtl->hif_rsp_rp),unsigned(rtl->hif_rsp_id)};
        }
        const uint64_t retired=rtl->response_retire_mask;
        for(unsigned t=0;t<64;t++) if((retired>>t)&1) {
            auto& x=observations[t];
            if(!x.active) SC_REPORT_FATAL("RtlAouTarget","unobserved RTL tag retirement");
            response_latencies.push_back(now-x.begin);
            events<<now<<",response_fdi_commit,"<<x.rp<<','<<x.id<<",0,"<<now-x.begin<<",0\n";
            x.active=false;
        }
        // Sample all payloads before the edge: RTL arbitration and RAM read
        // addresses are allowed to change immediately after that edge.
        rtl->clk=1;evaluate();dumpTrace();
        if(rx) {incoming.reset();++rx_flits;events<<now<<",fdi_rx,0,0,0,0,250\n";}
        if(cmd) {
            command_latencies.push_back(command_latency);
            events<<now<<",command,"<<unsigned(command->rp)<<','<<command->address.id<<",0,"<<command_latency<<','<<((uint64_t(1)<<command->address.size)*command->beats())<<'\n';
            if(command->write) {assembly=*command;assembly->write_beats.reserve(assembly->beats());++writes;}
            else {if(!mem_req.nb_write(*command)) SC_REPORT_FATAL("RtlAouTarget","reserved HIF read rejected");++reads;}
        }
        if(w) {
            if(!assembly || assembly->rp!=w_rp || last!=(assembly->write_beats.size()+1==assembly->beats()))
                SC_REPORT_FATAL("RtlAouTarget","HIF write framing mismatch");
            assembly->write_beats.push_back(*beat);++write_beats;
            events<<now<<",hif_w,"<<unsigned(assembly->rp)<<','<<assembly->address.id<<','
                <<assembly->write_beats.size()-1<<",0,"<<AXI_DATA_BYTES<<'\n';
            if(last) {
                if(!mem_req.nb_write(*assembly)) SC_REPORT_FATAL("RtlAouTarget","reserved HIF write rejected");
                assembly.reset();
            }
        }
        if(rsp) {
            if(!reply->rsp.write) {
                ++read_beats;
                events<<now<<",hif_r,"<<unsigned(reply->rsp.rp)<<','<<reply->rsp.id<<','
                    <<reply->beat<<",0,"<<AXI_DATA_BYTES<<'\n';
            }
            if(reply->rsp.write || ++reply->beat==reply->rsp.read_beats.size()) reply.reset();
        }
        if(tx) {
            FdiFlit f;f.payload.assign(bytes.begin(),bytes.end());f.valid_bytes=250;
            f.transaction_id=tx_id++;f.vc=0;f.kind=BusinessKind::Response;
            f.transaction_start=f.fdi_time=sc_time_stamp();
            if(!link_tx.nb_write(f)) SC_REPORT_FATAL("RtlAouTarget","reserved FDI FIFO rejected frame");
            ++tx_flits;events<<now<<",fdi_tx,0,0,0,0,250\n";
        }
    }
}
void RtlAouTarget::finish()
{
    if(finished) return;
    if(!idle()) SC_REPORT_FATAL("RtlAouTarget","bridge has unfinished business at exit");
    if(incoming) {++ignored_maintenance;incoming.reset();}
    FdiFlit f;
    while(link_rx.nb_read(f)) {
        if(!maintenanceOnly(f)) SC_REPORT_FATAL("RtlAouTarget","unconsumed business frame at exit");
        ++ignored_maintenance;
    }
    events.flush();if(trace) trace->flush();
    std::ofstream o(directory+"/storage_bridge_summary.json");
    o<<std::setprecision(17);
    o<<"{\"schema\":\"storagestacked.storage-bridge.v2\",\"implementation\":\"rtl\",\"business_idle\":true,"
      <<"\"link_idle\":"<<(rtl->link_idle?"true":"false")<<",\"ignored_verified_maintenance_frames\":"<<ignored_maintenance
      <<",\"clock_period_fs\":"<<period_fs<<",\"configuration\":{"
      <<"\"axi_data_width\":"<<rtl->config_axi_width<<",\"resource_planes\":"<<planes
      <<",\"request_slots_per_rp_direction\":"<<rtl->config_request_slots
      <<",\"max_outstanding\":"<<rtl->config_max_outstanding
      <<",\"wdata_granules\":"<<rtl->config_wdata_granules
      <<",\"frame_fifo_depth\":"<<rtl->config_frame_fifo_depth
      <<",\"tx_flush_cycles\":"<<rtl->config_tx_flush_cycles<<"},\"counters\":{";
#define BRIDGE_STAT(n) o<<"\"" #n "\":"<<rtl->stat_##n<<','
    BRIDGE_STAT(cycles);BRIDGE_STAT(rx_frames);BRIDGE_STAT(rx_messages);BRIDGE_STAT(tx_frames);
    BRIDGE_STAT(credit_wait_cycles);BRIDGE_STAT(cmd_stall_cycles);BRIDGE_STAT(w_stall_cycles);
    BRIDGE_STAT(tx_stall_cycles);BRIDGE_STAT(descriptor_depth_sum);BRIDGE_STAT(outstanding_depth_sum);
    BRIDGE_STAT(wdata_depth_sum);BRIDGE_STAT(wdata_peak);
    BRIDGE_STAT(descriptor_peak);BRIDGE_STAT(outstanding_peak);BRIDGE_STAT(rx_queue_peak);BRIDGE_STAT(tx_queue_peak);
    BRIDGE_STAT(packed_granules);BRIDGE_STAT(spanning_messages);BRIDGE_STAT(credit_only_frames);
#undef BRIDGE_STAT
    o<<"\"protocol_error\":"<<unsigned(rtl->protocol_error)<<"},\"latency\":{";
    auto distribution=[&](const char* name,std::vector<uint64_t> samples) {
        std::sort(samples.begin(),samples.end());
        o<<'"'<<name<<"\":{\"count\":"<<samples.size();
        if(!samples.empty()) {
            const long double sum=std::accumulate(samples.begin(),samples.end(),(long double)0);
            o<<",\"mean_fs\":"<<double(sum/samples.size());
            for(const auto& q: {std::pair<const char*,double>{"p50_fs",.50},{"p95_fs",.95},{"p99_fs",.99}})
                o<<",\""<<q.first<<"\":"<<samples.at(size_t(std::ceil(q.second*samples.size()))-1);
            o<<",\"max_fs\":"<<samples.back();
        }
        o<<'}';
    };
    distribution("request_frame_to_hif_command",command_latencies);o<<',';
    distribution("backend_response_to_fdi_commit",response_latencies);
    o<<"},\"power_status\":\"unmodeled; DRAMPower covers DRAM only\","
      <<"\"synthesis_status\":\"requires target tool and timing/library constraints\"}\n";
    finished=true;
}
} // namespace storage_axi
#endif
