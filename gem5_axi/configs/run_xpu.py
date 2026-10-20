"""Host-controlled Vortex/CoralNPU with all target memory behind AXI/UCIe."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shlex
import sys
from types import SimpleNamespace
import m5
from m5.objects import (AddrRange,AxiDemo,Root,SEWorkload,Process,System,SystemXBar,NoncoherentXBar,
                       SimpleMemory,SrcClockDomain,VoltageDomain,SystemC_Kernel,
                       Gem5ToTlmBridge64,HetAxiMonitor,MetricsMarker)
root_path=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('het_frontends',root_path/'gem5_new/gem5int/configs/het/het_system.py')
front=importlib.util.module_from_spec(spec);spec.loader.exec_module(front)
sys.path.insert(0, str(root_path/'env'))
from generate_ramulator_config import add_options
from topology_config import add_options as add_topology_options
from topology_config import write_resolved
sys.path.insert(0, str(root_path/'gem5_axi/configs'))
from system_builder import connect as connect_target, create_axi, load as load_system_topology
sys.path.insert(0, str(root_path/'gem5_axi/scripts'))
from collect_metrics import install as install_metrics
p=argparse.ArgumentParser()
add_options(p)
add_topology_options(p)
p.add_argument('--cmd',required=True)
p.add_argument('--options',default='')
p.add_argument('--vortex-library',default='')
p.add_argument('--vortex-host-rt-dir',default='')
p.add_argument('--npu-library',default='')
p.add_argument('--npu-kernel',default='')
p.add_argument('--num-cpus',type=int,default=4)
p.add_argument('--planes',type=int,choices=[1,2,3,4],default=2)
p.add_argument('--slots',type=int,default=16)
p.add_argument('--fdi-fifo-depth',type=int,default=8)
p.add_argument('--memory-fifo-depth',type=int,default=4)
p.add_argument('--no-stalls',action='store_true')
p.add_argument('--process-env-json',default='')
p.add_argument('--memsim-scale',type=int,default=1)
p.add_argument('--max-ticks',type=int,default=20_000_000_000_000)
p.add_argument('--replay',action='store_true')
p.add_argument('--axi-period',default='666667fs',
               help='AXI256 clock period; default matches the 48 GB/s UCIe raw capacity')
a=p.parse_args()
topology,link_count,port_count=load_system_topology(a)
args=SimpleNamespace(**vars(a),env=[],vortex_fast_forward=False,vortex_kernel='',
    vortex_bar_skew=0,npu_auto_start=False,npu_no_share=False)
for filename in (a.cmd,a.vortex_library,a.npu_library,a.npu_kernel):
    if filename and not Path(filename).is_file():raise RuntimeError('Missing '+filename)
if a.vortex_library and a.num_cpus<2:raise RuntimeError('Vortex runtime needs at least two CPU contexts')
if min(a.num_cpus,a.slots,a.fdi_fifo_depth,a.memory_fifo_depth)<1:raise RuntimeError('CPU/slot/FIFO values must be positive')
out=Path(m5.options.outdir).resolve();out.mkdir(parents=True,exist_ok=True)
write_resolved(topology,out)
m5.ticks.setGlobalFrequency('1fs')
(out/'hettrace').mkdir(exist_ok=True)
os.environ['HETTRACE_DIR']=str(out/'hettrace')
os.environ['HETTRACE_FILTER']='all'
os.environ['HETTRACE_FORMAT']='binary'
system=System()
system.clk_domain=SrcClockDomain(clock=front.HOST_CLOCK,voltage_domain=VoltageDomain())
system.mem_mode='timing'
system.membus=SystemXBar()
system.metrics_marker=MetricsMarker(trace_dir=str(out))
system.metrics_marker.pio=system.membus.mem_side_ports
system.system_port=system.membus.cpu_side_ports
host_range=AddrRange(front.HOST_HEAP[0],size=front.HOST_HEAP[1])
system.mem_ranges=[host_range]
system.host_mem=SimpleMemory(range=host_range,latency='10ns',conf_table_reported=True)
system.host_mem.port=system.membus.mem_side_ports
ranges=[AddrRange(front.SHARED_BUFFER[0],size=front.SHARED_BUFFER[1]),
        AddrRange(front.NPU_WORK[0],size=front.NPU_WORK[1])]
if a.vortex_library:ranges.append(AddrRange(front.VORTEX_BAR[0],size=front.VORTEX_BAR[1]))
size=0x170000000 if a.vortex_library else 0x30000000
create_axi(system,a,out,topology,base=0x90000000,size=size,period=a.axi_period,
    default_channels=8 if a.vortex_library else 2,outstanding=a.slots,
    planes=a.planes,stalls=not a.no_stalls,
    legacy_memory=dict(memsim_channels=8 if a.vortex_library else 2,
        memsim_scale=a.memsim_scale,memsim_queue=4,memsim_slots=8))
target_port=connect_target(system,topology,ranges,a.axi_data_width)
system.het_monitor=HetAxiMonitor(unique_packet_ids=True,trace_host=True,
    trace_vortex=bool(a.vortex_library),trace_coralnpu=bool(a.npu_library))
system.het_monitor.mem_side_port=target_port
system.het_monitor.cpu_side_port=system.membus.mem_side_ports
system.workload=SEWorkload.init_compatible(a.cmd)
env=front.host_env(args)
env.append('SS_METRICS_MARKERS=1')
if a.process_env_json:
    process_environment=json.loads(Path(a.process_env_json).read_text())
    if (not isinstance(process_environment,dict) or
            any(not isinstance(k,str) or not isinstance(v,str) for k,v in process_environment.items())):
        raise RuntimeError('--process-env-json must contain a string-to-string object')
    overridden=set(process_environment)
    env=[entry for entry in env if entry.split('=',1)[0] not in overridden]
    env.extend(f'{key}={value}' for key,value in process_environment.items())
if a.vortex_host_rt_dir:
    env=[s for s in env if not s.startswith('LD_LIBRARY_PATH=')]
    env.append('LD_LIBRARY_PATH='+a.vortex_host_rt_dir+':'+os.environ['SS_PREFIX']+'/lib')
process=Process(pid=100,cmd=[os.path.abspath(a.cmd)]+shlex.split(a.options),executable=os.path.abspath(a.cmd),env=env)
front.build_cpus(system,args,process)
if a.npu_library:front.build_npu(system,args)
if a.vortex_library:front.build_vortex(system,args)
if a.npu_library:system.coralnpu.metrics_dir=str(out)
if a.vortex_library:system.vortex.metrics_dir=str(out)
kernel=SystemC_Kernel(system=system)
root=Root(full_system=False,systemc_kernel=kernel)
metrics_context=install_metrics(out,a)
m5.instantiate()
front.map_device_windows(process,args)
process.map(0x70000000,0x70000000,4096,cacheable=False)
event=m5.simulate(a.max_ticks)
system.axi.finish()
metrics_context.update(end_tick_fs=m5.curTick(),exit_cause=event.getCause(),exit_code=event.getCode(),
                       completed=event.getCode()==0 and 'exiting with last active thread context' in event.getCause())
print('EXIT:',event.getCause(),'code',event.getCode(),'tick',m5.curTick())
if event.getCode()!=0 or 'exiting with last active thread context' not in event.getCause():
    raise RuntimeError('XPU workload did not finish successfully')
