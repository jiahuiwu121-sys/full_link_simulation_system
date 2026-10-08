'use strict';
const $=id=>document.getElementById(id),content=$('content'),palette=['#176ac6','#e38024','#23975d','#965bc4','#ca4367','#147c8d'];
const fmt=v=>v==null?'未测量/未启用':typeof v==='number'?Number(v.toPrecision(7)).toLocaleString('zh-CN'):String(v);
function element(tag,text,parent){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(parent)parent.appendChild(e);return e;}
function section(title,parent=content){const s=element('section',null,parent);element('h2',title,s);return s;}
function table(parent,head,rows){const scroll=element('div',null,parent);scroll.className='scroll';const t=element('table',null,scroll),tr=element('tr',null,element('thead',null,t));head.forEach(h=>element('th',h,tr));const b=element('tbody',null,t);for(const row of rows){const r=element('tr',null,b);for(const v of row){const c=element('td',null,r);if(v instanceof Node)c.appendChild(v);else c.textContent=fmt(v);}}}
function link(url,label){const a=element('a',label);a.href=url;return a;}
function cards(values,parent=content){const wrap=element('div',null,parent);wrap.className='cards';for(const [label,value]of values){const c=element('div',label,wrap);c.className='card';element('div',fmt(value),c).className='value';}}
function svgNode(tag,attrs,parent,text){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!=null)e.textContent=text;parent.appendChild(e);return e;}
function lines(parent,series,xLabel,yLabel){const valid=Object.entries(series).filter(([,v])=>v.length);if(!valid.length){element('p','没有可绘制的数据。',parent);return;}const svg=svgNode('svg',{viewBox:'0 0 720 280',role:'img','aria-label':yLabel+'随'+xLabel+'变化'},parent),xmax=Math.max(1,...valid.map(([,v])=>v[v.length-1][0])),ymax=Math.max(1e-12,...valid.map(([,v])=>v.reduce((m,p)=>Math.max(m,p[1]),0)))*1.08;const x=v=>64+v/xmax*628,y=v=>232-v/ymax*200;for(let i=0;i<=4;i++){const yy=232-i*50;svgNode('line',{x1:64,x2:692,y1:yy,y2:yy,stroke:'#e3eaf3'},svg);svgNode('text',{x:2,y:yy+4},svg,fmt(ymax*i/4));svgNode('text',{x:64+i*157,y:252,'text-anchor':i===4?'end':i===0?'start':'middle'},svg,fmt(xmax*i/4));}svgNode('text',{x:270,y:274},svg,xLabel+'；'+yLabel);const legend=element('div',null,parent);legend.className='legend';valid.forEach(([name,points],i)=>{svgNode('polyline',{points:points.map(p=>x(p[0])+','+y(p[1])).join(' '),fill:'none',stroke:palette[i%palette.length],'stroke-width':1.7},svg);const label=element('span',name,legend);label.style.color=palette[i%palette.length];});}
function bars(parent,pairs,unit){if(!pairs.length){element('p','没有可绘制的数据。',parent);return;}const width=720,height=Math.max(140,pairs.length*30+30),svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':unit+'对比'},parent),maximum=Math.max(1e-20,...pairs.map(p=>p[1]));pairs.forEach(([label,value],i)=>{svgNode('text',{x:3,y:i*30+23},svg,label.length>36?label.slice(0,12)+'…'+label.slice(-20):label);const r=svgNode('rect',{x:225,y:i*30+9,width:value/maximum*360,height:18,fill:palette[i%palette.length]},svg);svgNode('title',{},r,label+'：'+fmt(value)+' '+unit);svgNode('text',{x:592,y:i*30+23},svg,fmt(value));});}

const stageLabels={tlm_admission:'TLM接收等待',prefix_and_prior_segments:'到关键子请求的前缀（含之前分段）',backend_admission:'关键子请求提交等待',dram_queue_and_schedule:'关键子请求DRAM排队/调度',dram_data_service:'关键子请求DRAM数据服务',backend_return_wait:'服务后父响应等待',response_and_remaining_segments:'返回与剩余分段处理',tlm_response_hold:'TLM响应保持'};
const percent=v=>v==null?null:v*100;
function diagnosticPage(d){
 const x=d.diagnostics;
 if(!x){element('p','此结果尚未生成带宽/延迟诊断，重新运行或重新收集统计后可查看。',content).className='hint';return;}
 if(x.capacity_balance){const balance=section('模型容量平衡');
  cards([['判定',x.capacity_balance.status==='balanced_ingress'?'入口容量已平衡':'容量不平衡或信息不足'],['结构瓶颈',x.capacity_balance.bottleneck],...Object.entries(x.capacity_balance.capacities_Bps).map(([name,value])=>[name+' / GB/s',value==null?null:value/1e9])],balance);
  table(balance,['比例','值'],Object.entries(x.capacity_balance.ratios).map(([name,value])=>[name,value]));
  element('p','AXI与UCIe默认入口容量应在20%以内匹配；后端提交和DRAM数据总线应留有余量。这里展示模型上限，用于发现配置造成的假瓶颈，不代表工作负载已经达到该吞吐。',balance).className='hint';
 }
 const area=section('各段带宽与利用率'),windowSelect=element('select',null,area),overview=element('div',null,area);
 windowSelect.setAttribute('aria-label','带宽统计窗口');
 x.windows.forEach((w,i)=>{const option=element('option',w.name,windowSelect);option.value=i;});
 function windowDraw(){overview.replaceChildren();const w=x.windows[Number(windowSelect.value)];if(!w)return;
  cards([['窗口时间 / μs',(w.end_tick_fs-w.start_tick_fs)/1e9],['平均在途请求',w.inflight.time_weighted_mean],['最大在途请求',w.inflight.peak]],overview);
  table(overview,['接口/方向','模型峰值/GB/s','交付事件带宽/MB/s','占用率/%','占用口径'],x.resources.map(r=>{const v=w.resources[r.name];return[r.name,r.peak_Bps==null?null:r.peak_Bps/1e9,v.bandwidth_Bps==null?null:v.bandwidth_Bps/1e6,percent(v.utilization),r.occupancy_method||'没有单一峰值容量'];}));
  table(overview,['来源','完成请求','有效吞吐/MB/s','平均在途','最大在途'],Object.entries(w.sources).map(([name,v])=>[name,v.completed_requests,v.bandwidth_Bps==null?null:v.bandwidth_Bps/1e6,v.inflight.time_weighted_mean,v.inflight.peak]));
 }
 windowSelect.onchange=windowDraw;windowDraw();
 element('p','利用率按各段独立容量计算，不能相加或取平均作为整体利用率。AXI按复位后时钟握手机会统计；UCIe按序列化区间；DRAM按模型数据突发区间。字节带宽按接口交付事件计数，与占用时间在窗口边界可能不同。未知容量显示未测量。',area).className='hint';
 const ax=section('AXI状态与数据效率（全程）');
 cards([['AXI成功有效字节效率/%',percent(d.axi.successful_enabled_byte_efficiency)],['AXI2Flit请求侧装填效率/%',percent(d.axi2flit.packed_granule_utilization)]],ax);
 table(ax,['通道','成功握手/%','VALID等待READY/%','无VALID且READY/%','无VALID且无READY/%'],Object.entries(d.axi.channels||{}).map(([name,v])=>[name,percent(v.handshake_cycle_fraction),percent(v.stall_cycle_fraction),percent(d.axi.ready_idle_fractions?.[name]),percent(d.axi.blocked_idle_fractions?.[name])]));
 element('p','数据效率表示已使用的数据槽中有多少成功有效字节；装填效率表示Flit消息区域的装填程度。二者均不表示链路忙碌比例。无VALID可能来自负载不足或协议依赖，不能单独判定原因。',ax).className='hint';
 if(d.overall.amplification)table(ax,['传输层','传输字节/成功有效字节'],Object.entries(d.overall.amplification));
 table(ax,['UCIe方向','重放字节/B','重放字节占比/%'],x.resources.filter(r=>r.name.startsWith('UCIe')).map(r=>[r.name,r.replay_bytes,percent(r.replay_byte_fraction)]));
 const curves=section('全程带宽、占用率与并发时间曲线'),resourceSelect=element('select',null,curves),measureSelect=element('select',null,curves),curve=element('div',null,curves);
 resourceSelect.setAttribute('aria-label','带宽曲线接口');measureSelect.setAttribute('aria-label','带宽曲线指标');
 for(const r of x.resources)element('option',r.name,resourceSelect);
 for(const [value,label]of [['bandwidth_Bps','交付事件带宽 / MB/s'],['utilization','接口占用率 / %'],['inflight','平均在途请求']]){const op=element('option',label,measureSelect);op.value=value;}
 function curveDraw(){curve.replaceChildren();const field=measureSelect.value,name=resourceSelect.value;const points=x.timebins.map(b=>{let v=field==='inflight'?b.inflight.time_weighted_mean:b.resources[name]?.[field];if(v!=null)v*=field==='bandwidth_Bps'?1e-6:field==='utilization'?100:1;return[b.end_tick_fs/1e6,v];}).filter(p=>p[1]!=null);lines(curve,{[field==='inflight'?'全链路在途请求':name]:points},'模拟时间 / ns',field==='bandwidth_Bps'?'带宽 / MB/s':field==='utilization'?'占用率 / %':'平均在途请求');}
 resourceSelect.onchange=curveDraw;measureSelect.onchange=curveDraw;curveDraw();
 element('p',`曲线固定展示全程；每点为完整区间统计，实际区间宽度 ${fmt(x.binning.effective_bin_fs/1e6)} ns，最后一区间可能更短。最多1000个区间，长运行自动扩大区间；保留所有事件的总字节，不抽取峰值点。`,curves).className='hint';
 const cdf=section('成功请求延迟累计分布'),cdfSelect=element('select',null,cdf),cdfPlot=element('div',null,cdf);cdfSelect.setAttribute('aria-label','延迟分布来源与读写');
 for(const name of Object.keys(x.cdfs))element('option',name,cdfSelect);
 function cdfDraw(){cdfPlot.replaceChildren();lines(cdfPlot,{[cdfSelect.value]:x.cdfs[cdfSelect.value]||[]},'请求延迟 / ns','累计请求 / %');}cdfSelect.onchange=cdfDraw;cdfDraw();
 element('p','横轴为延迟，纵轴为不超过该延迟的成功请求比例。每组最多1000个经验分布点；精确分位数和样本数见统计表。',cdf).className='hint';
 const sizes=section('按来源、读写与请求大小查看完整延迟');table(sizes,['来源','读写','请求大小/B','状态','样本','平均/ns','P50/ns','P95/ns','P99/ns','最大/ns'],x.latency_by_size.map(r=>[r.source,r.command,r.requested_bytes,r.status===1?'成功':'错误',r.count,...['mean_fs','p50_fs','p95_fs','p99_fs','max_fs'].map(k=>r[k]==null?null:r[k]/1e6)]));
 const protocol=section('AXI与UCIe协议延迟');table(protocol,['指标','样本','平均/ns','P50/ns','P95/ns','P99/ns','最大/ns'],Object.entries(x.protocol_latency).map(([name,v])=>[name,v.count,...['mean_fs','p50_fs','p95_fs','p99_fs','max_fs'].map(k=>v[k]==null?null:v[k]/1e6)]));
 element('p','read_first_beat：AR到首个R；read_complete：AR到末个R；read_transfer：首个R到末个R；write_response：AW与全部W均接收后到B。UCIe logged_fdi_delivery 从发送模型记录的首次发送到接收交付，包含重放等待，不包含此前适配FIFO排队。',protocol).className='hint';
 const partition=section('完整请求延迟分解：关键子请求路径'),groupSelect=element('select',null,partition),partPlot=element('div',null,partition),partInfo=element('p',null,partition);
 groupSelect.setAttribute('aria-label','延迟分解来源与读写');const groups=x.critical_child_partition.groups;
 groups.forEach((g,i)=>{const op=element('option',g.source+'/'+g.command,groupSelect);op.value=i;});
 function partDraw(){partPlot.replaceChildren();const g=groups[Number(groupSelect.value)];if(!g){element('p','没有可关联的DRAM子请求。',partPlot);return;}bars(partPlot,x.critical_child_partition.stages.map(k=>[stageLabels[k],g.stages[k].mean_fs/1e6]),'平均 / ns');partInfo.textContent=`同一组 ${g.count} 个请求，平均完整延迟 ${fmt(g.total.mean_fs/1e6)} ns；这些阶段的平均值可以加和。`;}
 groupSelect.onchange=partDraw;partDraw();
 const tailSelect=element('select',null,partition),tailPlot=element('div',null,partition);tailSelect.setAttribute('aria-label','最长延迟请求示例');
 x.critical_child_partition.tail_examples.forEach((r,i)=>{const op=element('option',`UID ${r.uid} / ${r.source} / ${r.command} / ${fmt(r.total_fs/1e6)} ns`,tailSelect);op.value=i;});
 function tailDraw(){tailPlot.replaceChildren();const r=x.critical_child_partition.tail_examples[Number(tailSelect.value)];if(r)bars(tailPlot,x.critical_child_partition.stages.map(k=>[stageLabels[k],r[k]/1e6]),'ns');}tailSelect.onchange=tailDraw;tailDraw();
 element('p','每个请求选择最后完成SERVICE的子请求，构造互不重叠的完整时间分段。前缀与返回段包含其他AXI分段及协议处理，不能解读为纯UCIe延迟；并行子请求服务时间不能相加。各阶段P99不能相加。最长50个请求可在此查看，全部请求见延迟分解CSV。',partition).className='hint';
 const stalls=section('阻塞原因与等待比例');bars(stalls,x.stalls.filter(r=>r.fraction!=null&&r.fraction>0).map(r=>[r.module+'/'+r.reason,r.fraction*100]),'%');table(stalls,['模块','原因','阻塞周期','自身统计周期比例/%'],x.stalls.map(r=>[r.module,r.reason,r.cycles,percent(r.fraction)]));element('p','比例使用对应模块自身的统计周期。不同原因可能重叠，不能作为互斥执行时间相加；这些是全局计数，不能证明某个请求的长尾由该原因造成。',stalls).className='hint';
 const limits=section('统计边界与尚未覆盖项');table(limits,['项目','统计状态'],Object.entries(x.unavailable));if(x.warnings.length)element('p',x.warnings.join('；'),limits).className='bad';
 element('p','低利用率需要结合并发、背压和字节效率解释。traffic_steady_state 来自受控压力负载；普通CPU/GPU/NPU正确性用例仍不能单独代表链路饱和能力。',limits).className='hint';
}

function topologyPage(o){
 const topology=o.topology;if(!topology||!topology.links?.length)return;
 const s=section('并行拓扑与各物理路径');
 const resolved=topology.resolved||{},routing=resolved.routing||{},balance=topology.request_balance||{};
 cards([['模块数',topology.links.length],['路由策略',routing.policy],['地址条带/B',routing.stripe_bytes],['最少模块请求',balance.min],['最多模块请求',balance.max],['最大值/平均值',balance.max_to_mean]],s);
 table(s,['模块','名称','请求','有效吞吐/GB/s','AXI W/%','AXI R/%','UCIe正向/%','UCIe反向/%','后端bursts','DRAM子事务','DRAM命令','能量/μJ','功率/W'],topology.links.map(x=>{const m=x.metrics||{},u=m.ucie||{},name=resolved.modules?.find(v=>v.id===x.id)?.name;return[x.id,name,m.traffic?.requests,m.effective_bandwidth_Bps==null?null:m.effective_bandwidth_Bps/1e9,percent(m.axi_utilization?.W),percent(m.axi_utilization?.R),percent(u.forward?.physical_utilization),percent(u.reverse?.physical_utilization),m.backend_bursts,m.backend_children,m.dram_commands,m.dram_energy_j==null?null:m.dram_energy_j*1e6,m.dram_average_power_w];}));
 table(s,['模块','lanes','速率/GT/s','调制bit/UI','单向裸峰值/GB/s','正向物理带宽/GB/s','反向物理带宽/GB/s','正向新帧','正向重放','反向新帧','反向重放'],topology.links.map(x=>{const c=x.fabric?.link_config||{},m=x.metrics||{},u=m.ucie||{};return[x.id,c.lanes,c.rate_gtps,c.bits_per_symbol,m.ucie_raw_peak_Bps==null?null:m.ucie_raw_peak_Bps/1e9,u.forward?.physical_bandwidth_Bps==null?null:u.forward.physical_bandwidth_Bps/1e9,u.reverse?.physical_bandwidth_Bps==null?null:u.reverse.physical_bandwidth_Bps/1e9,u.forward?.new_flits,u.forward?.replay_flits,u.reverse?.new_flits,u.reverse?.replay_flits];}));
 element('p','每行是一条独立的 TLM→AXI→UCIe→memory-node 路径。UCIe利用率用实际物理发送位数除以该模块 lanes×GT/s×调制位数×仿真时间；AXI读写利用率用握手拍数除以复位释放后的可用时钟拍。DRAM能量可跨独立节点求和，请求延迟仍按每个原始请求统计。',s).className='hint';
}

async function casePage(d){const o=d.overall;$('status').textContent=`运行状态：${o.status}；独立统计校验：${d.check?.passed===true?'通过':'未完成/未通过'}`;
cards([['模拟时间 / μs',o.duration_seconds*1e6],['目标请求',o.traffic.requests],['有效字节 / B',o.effective_bytes],['全程有效吞吐 / MB/s',o.full_run_effective_bandwidth_Bps==null?null:o.full_run_effective_bandwidth_Bps/1e6],['DRAM能量 / μJ',o.dram_energy_j==null?null:o.dram_energy_j*1e6],['DRAM平均功率 / W',o.dram_average_power_w]]);
element('p','当前能量模型仅覆盖DRAM。全程、任务和kernel窗口口径不同；重叠窗口的能量不可相加。',content).className='hint';
topologyPage(o);
const plots=element('div',null,content);plots.className='plots';const p=section('DRAM区间平均功率',plots);lines(p,d.power,'模拟时间 / ns','功率 / W');const q=section('DRAM队列采样占用',plots),select=element('select',null,q),plot=element('div',null,q);for(const name of Object.keys(d.queues))element('option',name,select);const draw=()=>{plot.replaceChildren();lines(plot,{[select.value]:d.queues[select.value]||[]},'模拟时间 / ns','队列深度');};select.onchange=draw;draw();element('p',d.sampling_note,content).className='hint';
diagnosticPage(d);
const lat=section('请求延迟分位数 / ns');bars(lat,['mean_fs','p50_fs','p95_fs','p99_fs','max_fs'].filter(k=>o.latency[k]!=null).map(k=>[k.replace('_fs',''),o.latency[k]/1e6]),'ns');
const stage=section('按阶段、来源、读写查看延迟');table(stage,['阶段','来源','读写','样本','平均/ns','P50/ns','P95/ns','P99/ns','最大/ns'],d.latency.map(r=>[r.stage,r.source,r.command,Number(r.count),...['mean_fs','p50_fs','p95_fs','p99_fs','max_fs'].map(k=>r[k]===''?null:Number(r[k])/1e6)]));
const sources=section('各来源请求与流量');table(sources,['来源','请求','有效字节/B'],Object.entries(o.sources).map(([name,v])=>[name,v.requests,v.successful_enabled_bytes]));
const commands=section('实际DRAM命令分布');bars(commands,Object.entries(d.commands),'次');
const windows=section('任务与设备窗口');table(windows,['窗口','时间/μs','完成请求','有效吞吐/GB/s','请求P95/ns','DRAM能量/μJ','平均功率/W','边界方法'],o.window_statistics.map(w=>{const traffic=w.measurement_cohort_traffic||w.completed_target_traffic,bw=w.measurement_cohort_effective_bandwidth_Bps??w.completion_accounted_effective_bandwidth_Bps;return[w.name,w.duration_seconds*1e6,traffic.requests,bw==null?null:bw/1e9,traffic.latency.p95_fs==null?null:traffic.latency.p95_fs/1e6,w.dram_energy_j==null?null:w.dram_energy_j*1e6,w.dram_average_power_w,w.power_boundary_method];}));
const modules=section('独立模块报告'),choose=element('select',null,modules),details=element('pre',null,modules);for(const[name,v]of Object.entries(d.modules)){const option=element('option',name+' / '+v.status,choose);option.value=name;}let sequence=0;async function show(){const n=++sequence;try{const v=await get(d.modules[choose.value].report);if(n===sequence)details.textContent=JSON.stringify(v,null,2);}catch(e){details.textContent=e.message;}}choose.onchange=show;await show();}
function sweepPage(sweep){const s=section('带宽—延迟压力扫描');const rows=sweep.rows;
 lines(s,{'供给载荷':rows.map(r=>[r.load_percent,r.offered_payload_Bps/1e9]),'实测载荷':rows.map(r=>[r.load_percent,r.achieved_payload_Bps/1e9])},'供给负载 / %','吞吐 / GB/s');
 lines(s,{'P50':rows.map(r=>[r.load_percent,r.latency_p50_ns]),'P95':rows.map(r=>[r.load_percent,r.latency_p95_ns]),'P99':rows.map(r=>[r.load_percent,r.latency_p99_ns])},'供给负载 / %','请求延迟 / ns');
 table(s,['供给/%','实测/GB/s','P95/ns','平均在途','AXI W/%','AXI R/%','UCIe FWD/%','UCIe REV/%','后端提交/%','每tick最大提交'],rows.map(r=>[r.load_percent,r.achieved_payload_Bps/1e9,r.latency_p95_ns,r.inflight_mean,percent(r.axi_write_utilization),percent(r.axi_read_utilization),percent(r.ucie_forward_utilization),percent(r.ucie_reverse_utilization),percent(r.backend_ingress_utilization),r.max_submitted_per_tick]));
 element('p','拐点应同时查看吞吐增长放缓、P95延迟或在途请求上升，以及首先接近上限的链路资源。预热和排空阶段不计入这些数值。',s).className='hint';
}
function indexPage(d){$('status').textContent=`已收录 ${d.entries.length} 个用例；选择两项或多项可对比同一指标。`;element('p','不同工作负载、配置和统计窗口不能直接作为同条件对照。全程指标和稳态压力指标已分别标注，各用例不会相加。',content).className='hint';if(d.sweep)sweepPage(d.sweep);const s=section('运行记录'),filter=element('input',null,s);filter.placeholder='按批次或用例名称筛选';const holder=element('div',null,s),selection=new Set(),compare=section('选中用例对比'),metric=element('select',null,compare),plot=element('div',null,compare);const definitions={duration_seconds:['模拟时间 / μs',1e6],energy_j:['DRAM能量 / μJ',1e6],power_w:['DRAM平均功率 / W',1],bandwidth_Bps:['全程有效吞吐 / MB/s',1e-6],steady_bandwidth_Bps:['稳态有效吞吐 / GB/s',1e-9],offered_load_percent:['供给负载 / %',1],requests:['目标请求数',1],axi_write_utilization:['AXI写占用率 / %',100],axi_read_utilization:['AXI读占用率 / %',100],ucie_forward_utilization:['UCIe正向占用率 / %',100],ucie_reverse_utilization:['UCIe反向占用率 / %',100],p95_latency_ns:['全程请求P95延迟 / ns',1],steady_p95_latency_ns:['稳态请求P95延迟 / ns',1],p99_latency_ns:['请求P99延迟 / ns',1]};for(const[k,[label]]of Object.entries(definitions)){const option=element('option',label,metric);option.value=k;}function draw(){plot.replaceChildren();const [label,factor]=definitions[metric.value],pairs=[...selection].filter(v=>v[metric.value]!=null).map(v=>[v.run+'/'+v.case,v[metric.value]*factor]);bars(plot,pairs,label);}function render(){holder.replaceChildren();const rows=d.entries.filter(v=>(v.run+'/'+v.case).includes(filter.value)).map(v=>{const c=element('input');c.type='checkbox';c.checked=selection.has(v);c.onchange=()=>{if(c.checked)selection.add(v);else selection.delete(v);draw();};return[c,v.run,v.case,v.status,v.checked===true?'通过':'未校验/未通过',v.requests,v.offered_load_percent,v.steady_bandwidth_Bps==null?null:v.steady_bandwidth_Bps/1e9,v.steady_p95_latency_ns,v.duration_seconds*1e6,v.energy_j==null?null:v.energy_j*1e6,v.power_w,link(v.url,'打开报告')];});table(holder,['对比','批次','用例','状态','统计校验','请求','供给/%','稳态GB/s','稳态P95/ns','时间/μs','DRAM能量/μJ','平均功率/W','报告'],rows);}filter.oninput=render;metric.onchange=draw;render();draw();}
async function get(url){const response=await fetch(url,{cache:'no-store'});if(!response.ok)throw Error('HTTP '+response.status+'：'+url);return response.json();}
(async()=>{try{const kind=document.body.dataset.kind,d=await get(document.body.dataset.source);if(kind==='case')await casePage(d);else indexPage(d);}catch(error){$('status').textContent='加载失败：'+error.message+'。请使用 env/view_results.py 打开报告。';$('status').className='bad';}})();
