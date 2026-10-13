import {SharedStore,text,channelName,money,quantity,cleanName,uid,pyjson,blobValue,decodeBlob,mappingKey,feeKey,voucherGroups,erpPreview,dateString,priceKey,fraction,scaleFraction} from './core.mjs?v=20261013-1';
const $=id=>document.getElementById(id),escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const today=()=>new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Seoul'}),fmt=n=>Number(n||0).toLocaleString('ko-KR');
const store=new SharedStore({url:'https://jcslohuraqclhryeqxoc.supabase.co',key:'sb_publishable_dafbXHpLHVPDhsMwm_B5RA_LgCqlWeg'});
const ref=await fetch('/reference.json').then(r=>r.json());let page='orders',visible=[],timer=null,lastSync='',pollStopped=false;
const settings=()=>({...ref.defaults,...(store.records.get('settings:[]')?.payload||{})});
const orders=()=>store.rows('orders').map(o=>({...o,data:JSON.parse(o.data),components:JSON.parse(o.components)}));
const itemName=(code,fallback='')=>ref.items[code]||fallback;
const family=code=>{const override=store.find('mappings','voucher:v1:family:'+code,'key'),name=override?JSON.parse(override.components)[0]:ref.families[code];return name?'model:'+name:'sku:'+code;};
const selected=()=>[...document.querySelectorAll('input[data-row]:checked')].map(e=>visible[Number(e.dataset.row)]);
const badge=(value,green=false,red=false)=>`<span class="badge ${green?'green':red?'red':''}">${escape(value)}</span>`;
function notify(message){$('toast').textContent=message;$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,5000);}
function error(message){$('global-error').textContent=message;$('global-error').hidden=false;if($('modal').open){let field=$('modal-error');if(!field){field=document.createElement('p');field.id='modal-error';field.className='error';field.setAttribute('role','alert');$('modal-body').prepend(field);}field.textContent=message;}}
async function safe(action){$('global-error').hidden=true;try{await action();}catch(e){error(e.message);}}
function dialog(title,html){$('modal-title').textContent=title;$('modal-body').innerHTML=html;$('modal').showModal();}
$('modal-close').onclick=()=>{$('modal').close();$('modal-body').replaceChildren();};
$('modal').addEventListener('close',()=>{if(!$('modal').open)$('modal-body').replaceChildren();});
function download(bytes,name,mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'){const url=URL.createObjectURL(new Blob([bytes],{type:mime})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}
function workbook(headers,rows,sheet='출고요청'){const book=XLSX.utils.book_new(),ws=XLSX.utils.aoa_to_sheet([headers,...rows]);ws['!cols']=headers.map((_,i)=>({wch:i===7?45:20}));XLSX.utils.book_append_sheet(book,ws,sheet);return new Uint8Array(XLSX.write(book,{type:'array',bookType:'xlsx'}));}
const wekeepHeaders=['주문번호','판매처','상품명','수량','수령자','핸드폰','우편번호','주소','배송메세지','송장번호'];
const erpHeaders=['일자','순번','거래처코드','거래처명','담당자','출하창고','거래유형','통화','환율','계좌번호','미수금','특이사항','품목코드','품목명','규격','수량','단가','외화금액','공급가액','부가세','비고','생산전표생성'];
const wekeepRow=(d,c,tracking='')=>[d.order_no,channelName(d.channel),cleanName(itemName(c.code,c.name)),c.quantity,d.recipient,d.phone,d.postcode,d.address,d.memo,tracking];
function filtered(rows,getData=r=>r.data){const seller=$('channel').value,terms=$('search').value.toLowerCase().split(/\s+/).filter(Boolean);return rows.filter(r=>{const d=getData(r);return (!seller||channelName(d.channel)===seller)&&terms.every(t=>JSON.stringify([d,r.components,r.state]).toLowerCase().includes(t));});}
function table(headers,rows,select=true){return `<div class="table-wrap"><table><thead><tr>${select?'<th><input type="checkbox" id="select-all" aria-label="전체 선택"></th>':''}${headers.map(h=>`<th>${escape(h)}</th>`).join('')}<th>작업</th></tr></thead><tbody>${rows.length?rows.map((cells,i)=>`<tr>${select?`<td><input type="checkbox" data-row="${i}" aria-label="${i+1}번째 주문 선택"></td>`:''}${cells.map(c=>`<td>${c}</td>`).join('')}<td><button data-open="${i}">상세</button></td></tr>`).join(''):`<tr><td colspan="${headers.length+2}" class="empty">선택한 기간에 표시할 데이터가 없습니다.<br>날짜와 판매처를 확인하거나 주문 파일을 입력하세요.</td></tr>`}</tbody></table></div>`;}
function panel(title,actions,headers,rows,note=''){return `<div class="panel"><div class="panel-head"><div><h2>${title}</h2><small>표시 ${rows.length}건</small></div><div class="toolbar">${actions}</div></div>${table(headers,rows)}${note?`<div class="bottom-note">${note}</div>`:''}</div>`;}
const button=(id,label,primary=false)=>`<button id="${id}" class="${primary?'primary':''}">${label}</button>`;
function metrics(){const list=orders(),groups=voucherGroups(store,$('from').value,$('to').value);$('metrics').innerHTML=[['전체 주문',list.length,'건'],['출고 준비',list.filter(o=>o.state==='출고 준비').length,'건'],['출고 요청',list.filter(o=>o.state==='출고 요청').length,'건'],['미생성 전표',groups.filter(g=>!g.exported).length,'건']].map(([label,value,unit])=>`<div class="metric"><span>${label}</span><strong>${fmt(value)}<small>${unit}</small></strong></div>`).join('');}
function render(){
  if(!store.session)return;
  const current=$('channel').value,names=[...new Set([...orders().map(o=>channelName(o.data.channel)),...store.rows('smartstore_erp_rows').map(r=>channelName(JSON.parse(r.data).channel)),...store.rows('esm_erp_rows').map(r=>channelName(JSON.parse(r.data).channel))])].sort();
  $('channel').innerHTML='<option value="">전체 판매처</option>'+names.map(n=>`<option value="${escape(n)}">${escape(n)}</option>`).join('');$('channel').value=names.includes(current)?current:'';
  metrics();const from=$('from').value,to=$('to').value;
  if(page==='orders'){
    const requests=new Map(store.rows('requests').map(r=>[r.id,r.day])),days=new Map();for(const r of store.rows('request_lines'))days.set(r.order_id,requests.get(r.request_id));
    visible=filtered(orders().filter(o=>{const d=o.data._registered_day||days.get(o.id)||text(o.data.paid_at).slice(0,10);return d>=from&&d<=to;}));
    $('content').innerHTML=panel('판매처 주문',button('import','+ 주문 파일 입력',true)+button('match','상품 · 세트 매칭')+button('request','선택 출고요청 생성')+button('invoice','송장 파일 입력')+button('invoice-download','송장 포함 위킵 양식'),['판매처','주문번호','수령인','판매 상품 / 옵션','매칭 품목','수량','상태','송장번호'],visible.map(o=>[escape(channelName(o.data.channel)),escape(o.data.order_no),escape(o.data.recipient),escape(o.data.product+' / '+o.data.option),escape(o.components.map(c=>itemName(c.code,c.name)).join(' + ')),escape(o.data.quantity),badge(o.state,o.state==='출고 완료',!!o.issue),escape(o.data.tracking||'')]),'판매처별 원본을 입력하고 상품을 연결한 후 출고요청을 만드세요. 생성 파일은 공유 작업공간에 보관됩니다.');
    $('import').onclick=()=>safe(importDialog);$('match').onclick=()=>safe(()=>mappingDialog(selected()[0]));$('request').onclick=()=>safe(createRequest);$('invoice').onclick=()=>safe(invoiceImport);
    $('invoice-download').onclick=()=>safe(()=>{const list=requireSelection();if(list.some(o=>!o.components.length))throw Error('매칭된 주문을 선택하세요.');download(workbook(wekeepHeaders,list.flatMap(o=>o.components.map(c=>wekeepRow(o.data,c,o.data.tracking||'')))),'위킵_송장포함_'+today()+'.xlsx');});
  }else if(page==='shipping'){
    visible=filtered(voucherGroups(store,from,to));
    $('content').innerHTML=panel('출고 및 전표 작업표',button('confirm-shipment','출고요청 확인',true)+button('amount','선택 금액 입력')+button('preview','전표 미리보기')+button('reuse','기존 세트 금액 적용')+button('export','ERP 파일 생성',true),['출고일','판매처','품목','수량','상품금액','주문번호','상태'],visible.map(g=>[escape(g.day),escape(channelName(g.data.channel)),escape(g.components.map(c=>itemName(c.code,c.name)).join(' + ')||g.data.product),escape(g.components.map(c=>c.quantity).join(' / ')||g.data.quantity),fmt(g.components.length?g.components.reduce((a,c)=>a+Number(c.amount||0),0):money(g.data.amount||0)),escape(g.data.order_no),badge(g.exported?'이미 ERP 생성':g.issue||(!g.confirmed?'금액 확인 필요':'준비 완료'),g.confirmed&&!g.exported,!!g.issue)]),'실제 출고일과 전표일을 구분합니다. 이미 생성한 전표는 출력 이력에서 다시 내려받으세요.');
    $('confirm-shipment').onclick=()=>safe(shipmentDialog);$('amount').onclick=()=>safe(()=>amountDialog(selected()[0]));$('preview').onclick=()=>safe(()=>preview(false));$('export').onclick=()=>safe(()=>preview(true));$('reuse').onclick=()=>safe(reuseSplits);
    $('content').insertAdjacentHTML('beforeend','<div class="info">위킵 자동 조회는 기존 FLOW에서 실행할 수 있습니다. 동일 공유 작업공간으로 동기화한 송장번호는 웹에도 표시됩니다. 웹에서는 위킵 송장 파일을 직접 입력할 수 있습니다.</div>');
  }else if(page==='history'){
    visible=store.rows('artifacts').filter(a=>a.day>=from&&a.day<=to).sort((a,b)=>b.day.localeCompare(a.day));
    $('content').innerHTML=panel('생성 파일 이력',button('file-download','선택 파일 다운로드',true),['생성일','종류','파일 ID','ERP 등록 확인'],visible.map(a=>[escape(a.day),escape(a.kind),`<span class="mono">${escape(a.id)}</span>`,badge(a.registered?'등록 확인':'미확인',!!a.registered)]),'원본 파일은 다운로드할 때만 불러옵니다. 새로고침 시 파일 전체를 반복 조회하지 않습니다.');
    $('file-download').onclick=()=>safe(()=>downloadArtifact(selected()[0]));
  }else settingsPage();
  const all=$('select-all');if(all)all.onchange=()=>document.querySelectorAll('input[data-row]').forEach(e=>e.checked=all.checked);
  document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>safe(()=>openDetail(visible[Number(b.dataset.open)])));
}
async function sync(){if(!store.session)return;try{const changed=await store.sync();lastSync=new Date().toLocaleTimeString('ko-KR');$('sync-status').textContent='● 공유 연결 · '+lastSync;if(changed&&!$('modal').open)render();pollStopped=false;}catch(e){pollStopped=true;$('sync-status').textContent='동기화 중단';error(e.message);}}
async function commit(changes,message){await store.commit(changes);await sync();render();notify(message);}
function customer(channel){const key=channelName(channel),saved=settings().channel_customer_codes||{};return Object.entries(saved).find(([k])=>channelName(k)===key)?.[1]||ref.channels.find(r=>channelName(r.source_name)===key)?.ecount_customer_code||'';}
function mappingDialog(order){
  if(!order)throw Error('주문을 선택하세요.');if(!['출고 준비','검토 필요'].includes(order.state))throw Error('출고요청 전에 상품 매칭을 수정하세요.');
  const components=order.components.length?order.components:[{code:'',unit_amount:'0',warehouse:'300',customer:customer(order.data.channel)}];
  let entries=components.map(c=>({...c,unit_amount:c.unit_amount??'0'}));
  const show=()=>{
    dialog('상품 · 세트 매칭',`<p>${escape(order.data.product)} / ${escape(order.data.option)}</p><div class="info">색상에 맞는 활성 품목을 선택하세요. 첫 품목 금액은 원본 상품 총액에서 나머지 구성품 금액을 뺀 값으로 계산됩니다.</div><div id="components"></div><div class="dialog-actions">${button('add-component','+ 구성품 추가')}${button('save-mapping','매칭 저장',true)}</div>`);
    $('components').innerHTML=entries.map((c,i)=>`<div class="component"><label>품목 검색<input data-find="${i}" placeholder="모델명, 색상, 품목코드 검색" value="${escape(itemName(c.code,''))}"></label><div class="option-list" id="options-${i}"></div><div class="form-grid"><label>선택 품목코드<input data-code="${i}" readonly value="${escape(c.code)}"></label><label>부속품 개당 금액<input data-price="${i}" type="number" min="0" step="1" value="${escape(c.unit_amount)}" ${i===0?'readonly':''}></label><label>출하창고<select data-warehouse="${i}"><option value="300">300 위킵</option><option value="100" ${String(c.warehouse)==='100'?'selected':''}>100 본사</option></select></label></div>${i?`<button data-remove="${i}" class="danger">구성품 삭제</button>`:''}</div>`).join('');
    const suggestions=(i,q)=>{const terms=q.toLowerCase().split(/\s+/).filter(Boolean),list=Object.entries(ref.items).filter(([code,name])=>terms.every(t=>(code+' '+name).toLowerCase().includes(t))).slice(0,60);$('options-'+i).innerHTML=list.map(([code,name])=>`<button type="button" data-item="${escape(code)}">${escape(name)} <span class="muted">${escape(code)}</span></button>`).join('');$('options-'+i).querySelectorAll('button').forEach(b=>b.onclick=()=>{entries[i].code=b.dataset.item;document.querySelector(`[data-code="${i}"]`).value=b.dataset.item;document.querySelector(`[data-find="${i}"]`).value=itemName(b.dataset.item);$('options-'+i).replaceChildren();});};
    document.querySelectorAll('[data-find]').forEach(e=>{e.oninput=()=>suggestions(Number(e.dataset.find),e.value);});
    document.querySelectorAll('[data-price]').forEach(e=>e.oninput=()=>entries[Number(e.dataset.price)].unit_amount=e.value);
    document.querySelectorAll('[data-warehouse]').forEach(e=>e.onchange=()=>entries[Number(e.dataset.warehouse)].warehouse=e.value);
    document.querySelectorAll('[data-remove]').forEach(e=>e.onclick=()=>{entries.splice(Number(e.dataset.remove),1);$('modal').close();show();});
    $('add-component').onclick=()=>{entries.push({code:'',unit_amount:'0',warehouse:'300',customer:customer(order.data.channel)});$('modal').close();show();};
    $('save-mapping').onclick=()=>safe(async()=>{
      const q=quantity(order.data.quantity),total=money(order.data.amount||0),code=customer(order.data.channel);if(!code)throw Error('설정에서 이 판매처의 거래처코드를 먼저 입력하세요.');
      const fixed=entries.slice(1).reduce((a,c)=>a+money(c.unit_amount)*q,0);if(fixed>total)throw Error('부속품 금액이 상품 총금액보다 큽니다.');
      const cs=entries.map((c,i)=>{if(!ref.items[c.code])throw Error('활성 품목을 선택하세요.');return {...c,customer:code,name:itemName(c.code),logistics_code:c.code,quantity:q,source_quantity:q,amount:String(i===0?total-fixed:money(c.unit_amount)*q)};});
      const payload={...store.find('orders',order.id),components:JSON.stringify(cs),state:'출고 준비',issue:''},key=mappingKey(order.data);
      const saved=entries.map(c=>({...c,name:itemName(c.code),customer:code,logistics_code:c.code,quantity:1}));
      await commit([store.change('orders',payload),store.change('mappings',{key,components:JSON.stringify(saved)})],'상품 매칭을 저장했습니다.');$('modal').close();
    });
  };show();
}
function openDetail(row){
  if(page==='history'){dialog('출력 파일',`<p>${escape(row.kind)} · ${escape(row.day)}</p><p class="mono">${escape(row.id)}</p><div class="dialog-actions">${button('detail-download','다운로드',true)}</div>`);$('detail-download').onclick=()=>safe(()=>downloadArtifact(row));return;}
  if(page==='shipping'){amountDialog(row);return;}
  const d=row.data;dialog('주문 상세',`<div class="form-grid">${[['판매처',channelName(d.channel)],['주문번호',d.order_no],['수령인',d.recipient],['연락처',d.phone],['주소',d.address],['송장번호',d.tracking||'미입력'],['판매상품',d.product],['옵션',d.option]].map(([k,v])=>`<div><small class="muted">${k}</small><p>${escape(v)}</p></div>`).join('')}</div><div class="dialog-actions">${button('detail-match','상품 매칭',true)}</div>`);$('detail-match').onclick=()=>{$('modal').close();safe(()=>mappingDialog(row));};
}
async function downloadArtifact(row){if(!row)throw Error('파일을 선택하세요.');const full=await store.loadBlob('artifacts',row.id);download(decodeBlob(full.content),full.day+'_'+full.kind+'_'+full.id+'.xlsx');}
function requireSelection(){const list=selected();if(!list.length)throw Error('주문을 선택하세요.');return list;}
async function createRequest(){
  const list=requireSelection();if(list.some(o=>o.state!=='출고 준비'||!o.components.length))throw Error('출고 준비 상태의 매칭된 주문만 선택하세요.');
  const on=$('to').value;dateString(on);const batch='R-'+uid('').slice(0,12),changes=[],rows=[],stamp=new Date().toISOString().slice(0,19);
  const jid=batch;changes.push(store.change('requests',{id:batch,day:on}));
  for(const o of list){
    if(store.rows('request_lines').some(r=>r.order_id===o.id))throw Error('이미 출고요청이 있는 주문입니다.');
    for(const [index,c] of o.components.entries()){
      if(!ref.items[c.code])throw Error('사용하지 않는 품목이 포함됐습니다. 다시 매칭하세요.');
      const line=uid('L-');changes.push(store.change('request_lines',{id:line,request_id:batch,order_id:o.id,component:index,qty:quantity(c.quantity)}));rows.push(wekeepRow(o.data,c));
      changes.push(store.change('tracking_rows',{id:uid(''),job_id:jid,order_id:o.id,data:JSON.stringify({...o.data,product:cleanName(itemName(c.code,c.name)),quantity:String(c.quantity),_request_line_id:line,_original_data:o.data}),state:'pending',tracking:'',reason:'',evidence:'[]',queried_at:'',confirmed_at:'',confirmed_by:''}));
    }
    changes.push(store.change('orders',{...store.find('orders',o.id),state:'출고 요청'}));
  }
  const content=blobValue(workbook(wekeepHeaders,rows));changes.push(store.change('artifacts',{id:batch,kind:'출고요청',day:on,content,registered:0}));
  changes.push(store.change('tracking_jobs',{id:jid,identity:'request:'+batch,day:on,kind:'b2c',source_name:batch+'.xlsx',source_content:content,created_by:store.session.user.email,created_at:stamp}));
  await commit(changes,'출고요청을 공유 작업공간에 저장했습니다.');dialog('출고요청 생성 완료',`<p>${list.length}개 주문의 위킵 양식을 저장했습니다.</p><div class="info">파일 다운로드는 선택 사항입니다. 출력 이력에서도 내려받을 수 있습니다.</div><div class="dialog-actions">${button('request-download','위킵 양식 다운로드',true)}</div>`);$('request-download').onclick=()=>download(decodeBlob(content),on+'_위킵양식.xlsx');
}
function shipmentDialog(){
  const shipped=new Set(store.rows('shipments').map(s=>s.line_id)),requests=new Map(store.rows('requests').map(r=>[r.id,r.day])),os=new Map(orders().map(o=>[o.id,o])),groups=new Map();
  for(const r of store.rows('request_lines')){if(shipped.has(r.id))continue;const o=os.get(r.order_id),on=requests.get(r.request_id);if(!o||on<$('from').value||on>$('to').value)continue;if(!groups.has(o.id))groups.set(o.id,{order:o,lines:[]});groups.get(o.id).lines.push(r);}
  const list=[...groups.values()];dialog('실제 출고 확인',`<label>실제 출고일<input id="actual-day" type="date" value="${today()}"></label><div class="info">실제로 출고한 주문만 선택하세요. 송장 조회와 출고 확정은 별개입니다.</div>${list.map((g,i)=>`<p><label><input type="checkbox" data-confirm="${i}" style="width:16px">${escape(channelName(g.order.data.channel)+' · '+g.order.data.order_no+' · '+g.order.data.recipient)}</label></p>`).join('')||'<p>확인할 출고요청이 없습니다. 요청일 조회 범위를 확인하세요.</p>'}<div class="dialog-actions">${button('save-shipment','선택 출고 확정',true)}</div>`);
  $('save-shipment').onclick=()=>safe(async()=>{
    const chosen=[...document.querySelectorAll('[data-confirm]:checked')].map(e=>list[Number(e.dataset.confirm)]);if(!chosen.length)throw Error('실제 출고한 주문을 선택하세요.');const day=dateString($('actual-day').value),changes=[];
    for(const g of chosen){for(const line of g.lines){const c=g.order.components[line.component];changes.push(store.change('shipments',{id:uid(''),line_id:line.id,qty:line.qty,tracking:g.order.data.tracking||'',day,erp_id:null,erp_amount:String(money(c.amount||0)),erp_code:null,erp_name:null,erp_warehouse:null,amount_split_confirmed:g.order.components.length===1?1:0}));}changes.push(store.change('orders',{...store.find('orders',g.order.id),state:'출고 완료'}));}
    await commit(changes,'실제 출고를 확정했습니다.');$('modal').close();
  });
}
function fullSet(g){if(g.kind!=='shipment')return true;const order=orders().find(o=>o.id===g.order_id);return order&&order.components.length===g.components.length&&g.components.every(c=>Number(c.quantity)===Number(order.components[c.index]?.quantity));}
function amountDialog(group){
  if(!group)throw Error('전표 주문을 선택하세요.');if(group.exported)throw Error('이미 생성한 주문입니다. 출력 이력을 확인하세요.');
  if(group.issue||!group.components.length){if(group.kind==='smartstore'||group.kind==='esm'){erpMapping(group);return;}throw Error('상품 매칭부터 확인하세요.');}
  const total=group.components.reduce((a,c)=>a+money(c.amount||0),0),values=group.components;
  dialog('상품 · 세트 금액 입력',`<p>${escape(channelName(group.data.channel)+' · '+group.data.order_no+' · '+group.data.recipient)}</p>${group.kind!=='shipment'?button('change-erp-set','상품 · 세트 구성 변경'):''}<label>이번 출고 상품 총금액 (배송비 제외)<input id="amount-total" type="number" min="0" step="1" value="${total}"></label>${values.map((c,i)=>`<div class="component"><b>${escape(itemName(c.code,c.name))}</b><p class="hint">${escape(c.code)} · 수량 ${c.quantity} · 색상 공유 그룹 ${escape(family(c.code))}</p><label>구성품 총금액<input data-amount="${i}" type="number" min="0" step="1" value="${money(c.amount||0)}"></label></div>`).join('')}<label>주문 배송비<input id="amount-fee" type="number" min="0" step="1" value="${money(group.data.shipping||0)}"></label><div id="amount-difference" class="info"></div><label><input id="remember" type="checkbox" checked style="width:16px">같은 구성·판매금액의 다른 색상에도 기준 저장</label><div class="dialog-actions">${button('save-amount','금액 확정',true)}</div>`);
  if($('change-erp-set'))$('change-erp-set').onclick=()=>{$('modal').close();erpMapping(group);};
  const update=()=>{const inputs=[...document.querySelectorAll('[data-amount]')];if(inputs.length===1)inputs[0].value=$('amount-total').value;try{$('amount-difference').textContent='상품 총금액과 차이 '+fmt(money($('amount-total').value)-inputs.reduce((a,c)=>a+money(c.value),0))+'원';}catch{$('amount-difference').textContent='0 이상의 정수를 입력하세요.';}};
  $('amount-total').oninput=update;document.querySelectorAll('[data-amount]').forEach(e=>e.oninput=update);update();
  $('save-amount').onclick=()=>safe(async()=>{
    const total=money($('amount-total').value),amounts=[...document.querySelectorAll('[data-amount]')].map(e=>money(e.value));if(amounts.reduce((a,b)=>a+b,0)!==total)throw Error('구성품 합계가 상품 총금액과 같아야 합니다.');
    const changes=amountChanges(group,amounts),key=feeKey(group.data),fee=money($('amount-fee').value);
    if(!store.find('fees',key,'bundle'))changes.push(store.change('mappings',{key:'voucher:v1:fee:'+key,components:JSON.stringify([String(fee)])}));
    const rk=fullSet(group)&&values.length>1?await priceKey(group.data,group.components,family,total):null;
    if($('remember').checked&&rk){const count=quantity(group.data.quantity),allocation=Object.fromEntries(values.map((c,i)=>[family(c.code),fraction(amounts[i],count)])),previous=store.find('mappings',rk,'key'),variants=previous?JSON.parse(previous.components):[];if(!variants.some(v=>JSON.stringify(Object.entries(v).sort())===JSON.stringify(Object.entries(allocation).sort())))variants.push(allocation);changes.push(store.change('mappings',{key:rk,components:JSON.stringify(variants)}));}
    await commit(changes,'전표 금액을 저장했습니다.');$('modal').close();
  });
}
function amountChanges(g,amounts){
  if(g.kind==='shipment')return g.components.map((c,i)=>store.change('shipments',{...store.find('shipments',c.entry_id),erp_amount:String(amounts[i]),amount_split_confirmed:1}));
  const table=g.kind==='smartstore'?'smartstore_erp_rows':'esm_erp_rows',r=store.find(table,g.order_id),components=JSON.parse(r.components);components.forEach((c,i)=>c.amount=String(amounts[i]));return [store.change(table,{...r,components:JSON.stringify(components),...(g.kind==='smartstore'?{amount_split_confirmed:1}:{})})];
}
function erpMapping(group){
  let cs=group.components.length?group.components.map(c=>({...c,perSet:Number(c.quantity)/quantity(group.data.quantity),amount:money(c.amount||0)})):[{code:'',perSet:1,amount:money(group.data.amount||0),warehouse:'300'}];
  const show=()=>{
    dialog('전표 품목 · 세트 연결',`<p>${escape(group.data.product+' / '+group.data.option)}</p><label>상품 총금액<input id="erp-total" type="number" value="${money(group.data.amount||0)}" min="0"></label><label>거래처코드<input id="erp-customer" value="${escape(cs[0].customer||customer(group.data.channel))}"></label><div id="erp-components"></div><div class="dialog-actions">${button('erp-add','+ 세트 구성품 추가')}${button('erp-connect','구성 · 금액 확정',true)}</div>`);
    $('erp-components').innerHTML=cs.map((c,i)=>`<div class="component"><label>품목 검색<input data-erp-search="${i}" value="${escape(itemName(c.code))}" placeholder="모델명 · 색상"></label><div class="option-list" id="erp-options-${i}"></div><p class="hint">선택: <span id="erp-selected-${i}">${escape(c.code||'품목을 선택하세요.')}</span></p><div class="form-grid"><label>세트당 수량<input data-erp-q="${i}" type="number" min="1" step="1" value="${c.perSet}"></label><label>해당 구성품 총금액<input data-erp-amount="${i}" type="number" min="0" step="1" value="${c.amount}"></label><label>창고<select data-erp-warehouse="${i}"><option value="300">300 위킵</option><option value="100" ${String(c.warehouse)==='100'?'selected':''}>100 본사</option></select></label></div>${i?`<button data-erp-remove="${i}" class="danger">삭제</button>`:''}</div>`).join('');
    document.querySelectorAll('[data-erp-search]').forEach(e=>e.oninput=()=>{const i=Number(e.dataset.erpSearch),terms=e.value.toLowerCase().split(/\s+/).filter(Boolean);$('erp-options-'+i).innerHTML=Object.entries(ref.items).filter(([code,name])=>terms.every(t=>(code+' '+name).toLowerCase().includes(t))).slice(0,60).map(([code,name])=>`<button data-code="${escape(code)}">${escape(name+' · '+code)}</button>`).join('');$('erp-options-'+i).querySelectorAll('button').forEach(b=>b.onclick=()=>{cs[i].code=b.dataset.code;e.value=itemName(b.dataset.code);$('erp-selected-'+i).textContent=b.dataset.code;$('erp-options-'+i).replaceChildren();});});
    for(const [attribute,field] of [['erp-q','perSet'],['erp-amount','amount'],['erp-warehouse','warehouse']])document.querySelectorAll('[data-'+attribute+']').forEach(e=>e.oninput=()=>cs[Number(e.getAttribute('data-'+attribute))][field]=e.value);
    document.querySelectorAll('[data-erp-remove]').forEach(e=>e.onclick=()=>{cs.splice(Number(e.dataset.erpRemove),1);$('modal').close();show();});
    $('erp-add').onclick=()=>{if(cs.length>=5)throw Error('세트는 최대 5개 구성품을 사용하세요.');cs.push({code:'',perSet:1,amount:0,warehouse:'300'});$('modal').close();show();};
    $('erp-connect').onclick=()=>safe(async()=>{const code=text($('erp-customer').value),total=money($('erp-total').value),q=quantity(group.data.quantity);if(!code)throw Error('거래처코드를 입력하세요.');if(cs.reduce((a,c)=>a+money(c.amount),0)!==total)throw Error('구성품 금액 합계가 상품 총금액과 같아야 합니다.');const components=cs.map(c=>{if(!ref.items[c.code])throw Error('모든 활성 품목을 선택하세요.');return {code:c.code,logistics_code:c.code,name:itemName(c.code),quantity:q*quantity(c.perSet),amount:String(money(c.amount)),warehouse:c.warehouse,customer:code};});const table=group.kind==='smartstore'?'smartstore_erp_rows':'esm_erp_rows',r=store.find(table,group.order_id);await commit([store.change(table,{...r,components:JSON.stringify(components),issue:'',...(group.kind==='smartstore'?{amount_split_confirmed:1}:{})})],'전표 구성과 금액을 연결했습니다.');$('modal').close();});
  };show();
}
async function reuseSplits(){const changes=[];let count=0;for(const g of voucherGroups(store,$('from').value,$('to').value)){if(g.exported||g.confirmed||g.issue||g.components.length<2||!fullSet(g))continue;const key=await priceKey(g.data,g.components,family,g.data.amount||0),rule=key&&store.find('mappings',key,'key');if(!rule)continue;const variants=JSON.parse(rule.components);if(variants.length!==1)continue;let amounts;try{amounts=g.components.map(c=>scaleFraction(variants[0][family(c.code)],quantity(g.data.quantity)));}catch{continue;}if(amounts.reduce((a,b)=>a+b,0)!==money(g.data.amount||0))continue;changes.push(...amountChanges(g,amounts));count++;}if(changes.length)await commit(changes,`${count}건의 세트 금액을 적용했습니다.`);else notify('동일한 구성·판매금액의 저장된 기준이 없습니다.');}
function preview(exportFile){
  const selection=selected(),ids=(selection.length?selection:visible).map(g=>g.id),on=today(),result=erpPreview(store,$('from').value,$('to').value,on,{ids}),total=result.rows.reduce((a,r)=>a+r[15]*r[16],0);
  dialog('전표 미리보기',`<label>ERP 전표일<input id="voucher-day" type="date" value="${on}"></label><div class="totals"><b>상품·배송비 포함 ${fmt(total)}원</b><span>${result.rows.length}개 전표 행</span></div><div class="table-wrap"><table><thead><tr>${['거래처','품목코드','품목명','수량','단가','총금액'].map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${result.rows.map(r=>`<tr>${[r[2],r[12],r[13],r[15],fmt(r[16]),fmt(r[15]*r[16])].map(v=>`<td>${escape(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div><div class="dialog-actions">${button('save-erp','공유 저장 후 ERP 다운로드',true)}</div>`);
  $('save-erp').onclick=()=>safe(async()=>{
    const on=dateString($('voucher-day').value),r=erpPreview(store,$('from').value,$('to').value,on,{ids}),batch='E-'+uid('').slice(0,12),changes=[],content=blobValue(workbook(erpHeaders,r.rows,'이카운트 웹입력'));
    for(const g of r.groups){if(g.kind==='shipment')for(const c of g.components)changes.push(store.change('shipments',{...store.find('shipments',c.entry_id),erp_id:batch}));else{const table=g.kind==='smartstore'?'smartstore_erp_rows':'esm_erp_rows';changes.push(store.change(table,{...store.find(table,g.order_id),erp_id:batch}));}}
    changes.push(...r.fees.map(f=>store.change('fees',{...f,erp_id:batch})),store.change('artifacts',{id:batch,kind:'ERP',day:on,content,registered:0}));
    await commit(changes,'ERP 파일과 반영 이력을 저장했습니다.');download(decodeBlob(content),'ERP_'+on+'.xlsx');$('modal').close();
  });
}

function importDialog(){
  const profiles=settings().profiles.filter(p=>p.enabled!==false&&(p.purpose||'order')==='order');
  dialog('판매처 주문 파일 입력',`<label>판매처<select id="import-channel">${profiles.map((p,i)=>`<option value="${i}">${escape(channelName(p.channel))}</option>`).join('')}</select></label><label>등록 작업일<input id="import-day" type="date" value="${today()}"></label><div class="upload-box"><input id="order-file" type="file" accept=".xlsx,.xls,.csv"></div><div id="column-preview"></div>`);
  $('order-file').onchange=()=>safe(async()=>{
    const file=$('order-file').files[0];if(!file)return;if(file.size>8000000)throw Error('파일은 8MB 이하로 나누어 입력하세요.');
    const profile=profiles[Number($('import-channel').value)],bytes=new Uint8Array(await file.arrayBuffer()),book=XLSX.read(bytes,{type:'array'}),sheet=book.SheetNames[0],rows=XLSX.utils.sheet_to_json(book.Sheets[sheet],{header:1,raw:false,defval:''});
    const norm=v=>text(v).toLowerCase().replace(/[^0-9a-z가-힣]/g,''),fields=[['order_no','주문번호'],['line_no','상품주문번호'],['product','상품명'],['option','옵션'],['quantity','수량'],['amount','상품 총금액'],['recipient','수령인'],['phone','연락처'],['postcode','우편번호'],['address','주소'],['memo','배송메모'],['shipping','배송비'],['bundle','묶음번호']];
    const columns=profile.columns||{},header=rows.slice(0,30).map((r,i)=>[r,i,fields.filter(([k])=>(columns[k]||[]).some(h=>r.some(v=>norm(v)===norm(h)))).length]).sort((a,b)=>b[2]-a[2])[0];
    if(!header||header[2]<3)throw Error('주문 헤더를 찾지 못했습니다. 설정의 판매처 열 정보를 확인하세요.');
    const [headers,offset]=header;
    $('column-preview').innerHTML=`<div class="info">열 연결을 확인한 뒤 입력하세요. 수량·상품 금액은 원본 총액 기준입니다.</div><div class="form-grid">${fields.map(([k,label])=>{const index=headers.findIndex(v=>(columns[k]||[]).some(h=>norm(h)===norm(v)));return `<label>${label}<select data-column="${k}"><option value="-1">미사용</option>${headers.map((h,i)=>`<option value="${i}" ${i===index?'selected':''}>${escape(h||'빈 열')} (${i+1}열)</option>`).join('')}</select></label>`;}).join('')}</div><div class="dialog-actions">${button('import-save','확인 후 주문 입력',true)}</div>`;
    $('import-save').onclick=()=>safe(async()=>{
      const chosen=Object.fromEntries([...document.querySelectorAll('[data-column]')].map(e=>[e.dataset.column,Number(e.value)])),on=dateString($('import-day').value),sourceName=file.name.replace(/(\.[^.]+)?$/,m=>'_web_'+uid('').slice(0,8)+m),changes=[],existing=orders();let count=0;
      for(const [position,raw] of rows.slice(offset+1).entries()){
        if(raw.every(v=>!text(v)))continue;
        const d=Object.fromEntries(fields.map(([k])=>[k,chosen[k]<0?'':text(raw[chosen[k]])]));
        if(!d.order_no&&!d.product)continue;
        for(const k of ['order_no','product','quantity','recipient','phone','address'])if(!d[k])throw Error(`${offset+position+2}행 ${k} 값이 없습니다.`);
        d.line_no ||= d.order_no+':'+(offset+position+2);d.quantity=String(quantity(d.quantity));d.amount=String(money(d.amount||0));d.shipping=String(money(d.shipping||0));
        if(profile.amount_is_unit)d.amount=String(money(d.amount)*quantity(d.quantity));
        Object.assign(d,{channel:profile.channel,account:profile.account||'기본',source_file:sourceName,source_row:offset+position+2,source_sheet:sheet,_registered_day:on,paid_at:'',status:''});
        const same=existing.find(o=>o.data.channel===d.channel&&o.data.account===d.account&&o.data.line_no===d.line_no);
        if(same){if(['order_no','product','option','quantity','amount','recipient','phone','address'].some(k=>text(same.data[k])!==text(d[k])))throw Error('같은 상품주문번호의 내용이 다릅니다. 기존 주문을 확인하세요: '+d.line_no);continue;}
        const definition=store.find('mappings',mappingKey(d),'key');let cs=[],issue='상품 매칭 필요';
        if(definition){const defs=JSON.parse(definition.components),q=quantity(d.quantity),fixed=defs.slice(1).reduce((a,c)=>a+money(c.unit_amount||0)*q,0);if(defs.every(c=>ref.items[c.code])&&fixed<=money(d.amount)){cs=defs.map((c,i)=>({...c,name:itemName(c.code),quantity:q,source_quantity:q,amount:String(i===0?money(d.amount)-fixed:money(c.unit_amount||0)*q)}));issue='';}}
        const id=uid('');changes.push(store.change('orders',{id,identity:pyjson([d.channel,d.account,d.line_no]),data:JSON.stringify(d),components:JSON.stringify(cs),state:issue?'검토 필요':'출고 준비',issue}));existing.push({id,data:d});count++;
      }
      if(!count){notify('이미 입력된 주문입니다.');return;}
      changes.push(store.change('source_files',{name:sourceName,content:blobValue(bytes)},sourceName));
      await commit(changes,`${count}개 주문을 저장했습니다.`);$('modal').close();
    });
  });
}
function invoiceImport(){
  dialog('위킵 송장 파일 입력','<div class="info">주문번호와 수령인·연락처가 일치하고 송장이 한 개로 확인되는 주문만 반영합니다. 출고·ERP 상태는 변경하지 않습니다.</div><input id="invoice-file" type="file" accept=".xlsx,.xls,.csv">');
  $('invoice-file').onchange=()=>safe(async()=>{
    const file=$('invoice-file').files[0],book=XLSX.read(await file.arrayBuffer(),{type:'array'}),rows=XLSX.utils.sheet_to_json(book.Sheets[book.SheetNames[0]],{raw:false,defval:''}),changes=[];let count=0;
    for(const o of orders()){
      const matches=rows.filter(r=>text(r['주문번호'])===text(o.data.order_no)&&text(r['수령자']||r['수령인'])===text(o.data.recipient)&&text(r['핸드폰']||r['연락처']).replaceAll('-','')===text(o.data.phone).replaceAll('-',''));
      const invoices=[...new Set(matches.map(r=>text(r['송장번호'])).filter(Boolean))];if(invoices.length!==1||o.data.tracking&&o.data.tracking!==invoices[0])continue;
      changes.push(store.change('orders',{...store.find('orders',o.id),data:JSON.stringify({...o.data,tracking:invoices[0]})}));count++;
      for(const r of store.rows('tracking_rows').filter(r=>r.order_id===o.id&&r.state!=='confirmed'))changes.push(store.change('tracking_rows',{...r,state:'confirmed',tracking:invoices[0],reason:'웹 송장 파일 일치',confirmed_at:new Date().toISOString().slice(0,19),confirmed_by:store.session.user.email}));
    }
    if(!changes.length)throw Error('안전하게 일치하는 송장을 찾지 못했습니다. 주문번호·수령인·연락처를 확인하세요.');
    await commit(changes,`${count}개 주문에 송장을 반영했습니다.`);$('modal').close();
  });
}
function settingsPage(){
  $('content').innerHTML=`<div class="grid-two"><div class="panel settings-block"><h3>공유 작업공간</h3><p>기존 FLOW와 같은 Supabase 작업공간을 사용합니다. 로그인한 작업자의 권한으로 읽고 저장하며, 변경 행만 동기화합니다.</p><p>현재 계정: ${escape(store.session.user.email)}</p>${button('backup','공유 데이터 백업 다운로드')}</div><div class="panel settings-block"><h3>공동 개발</h3><p>웹 소스는 기존 FLOW 저장소의 web 폴더에서 관리합니다. heetae1120 계정의 GitHub 협업 권한을 유지합니다.</p><a href="https://github.com/heetae1120/REQMFLOW/tree/main/web" target="_blank" rel="noopener">웹 소스 열기 ↗</a></div><div class="panel settings-block"><h3>판매처 거래처코드</h3><p>전표 출력에 사용할 거래처코드를 관리합니다.</p>${button('customers','거래처코드 편집')}</div><div class="panel settings-block"><h3>품목 · 색상 공유 그룹</h3><p>활성 품목 ${Object.keys(ref.items).length}개를 사용합니다. 색상 공유 그룹은 모델·용량·길이가 같은 품목끼리 지정하세요.</p>${button('families','색상 공유 그룹 관리')}</div><div class="panel settings-block"><h3>판매처 파일 열 설정</h3><p>판매처별 파일 헤더 연결은 기존 FLOW 설정과 공유합니다. 주문 입력 시 연결된 열을 다시 확인할 수 있습니다.</p>${button('profiles','판매처 열 정보 확인')}</div><div class="panel settings-block"><h3>위킵 · 판매처 자동화</h3><p>외부 판매처 로그인·다운로드와 위킵 자동 조회는 기존 FLOW 프로그램에서 실행합니다. 공유 동기화 후 결과를 웹에서 함께 확인하세요.</p><a href="https://github.com/heetae1120/REQMFLOW/releases/latest" target="_blank" rel="noopener">FLOW 프로그램 다운로드 ↗</a></div></div>`;
  $('backup').onclick=()=>safe(async()=>{const data={format:'reqm-flow-web-record-backup-v1',created_at:new Date().toISOString(),workspace:'default',records:[...store.records.values()].filter(r=>!r.metadataOnly)};download(new TextEncoder().encode(JSON.stringify(data)),'FLOW_공유데이터_'+today()+'.json','application/json');notify('백업은 작업 데이터와 설정이며 파일 원본은 출력 이력에서 별도 다운로드하세요.');});
  $('customers').onclick=()=>{const current=settings().channel_customer_codes||{};dialog('판매처 거래처코드',`<div class="form-grid">${settings().profiles.filter(p=>(p.purpose||'order')==='order').map(p=>`<label>${escape(channelName(p.channel))}<input data-customer="${escape(p.channel)}" value="${escape(current[p.channel]||customer(p.channel))}"></label>`).join('')}</div><div class="dialog-actions">${button('save-customers','저장',true)}</div>`);$('save-customers').onclick=()=>safe(async()=>{const payload={...(store.records.get('settings:[]')?.payload||settings()),channel_customer_codes:Object.fromEntries([...document.querySelectorAll('[data-customer]')].map(e=>[e.dataset.customer,text(e.value)]))};delete payload.cloud_email;await commit([{row_key:'settings:[]',table_name:'settings',payload,deleted:false,expected_revision:store.records.get('settings:[]')?.revision||0}],'거래처코드를 저장했습니다.');$('modal').close();});};
  $('families').onclick=()=>{dialog('색상 공유 그룹',`<div class="info">빈 값은 금액 공유를 끕니다. 모델·용량·길이가 다르면 같은 그룹으로 묶지 마세요.</div><div class="form-grid">${Object.entries(ref.items).map(([c,n])=>`<label>${escape(n)}<input data-family="${escape(c)}" value="${escape(family(c).startsWith('sku:')?'':family(c).replace(/^model:/,''))}"></label>`).join('')}</div><div class="dialog-actions">${button('save-families','변경 그룹 저장',true)}</div>`);$('save-families').onclick=()=>safe(async()=>{const changes=[...document.querySelectorAll('[data-family]')].filter(e=>text(e.value)!==(family(e.dataset.family).startsWith('sku:')?'':family(e.dataset.family).replace(/^model:/,''))).map(e=>store.change('mappings',{key:'voucher:v1:family:'+e.dataset.family,components:JSON.stringify([text(e.value)])}));if(changes.length)await commit(changes,'색상 공유 그룹을 저장했습니다.');$('modal').close();});};
  $('profiles').onclick=()=>dialog('판매처별 파일 열 정보',settings().profiles.filter(p=>(p.purpose||'order')==='order').map(p=>`<div class="component"><b>${escape(channelName(p.channel))}</b><p>${escape(Object.entries(p.columns||{}).map(([k,v])=>k+': '+v.join(' / ')).join(' · '))}</p></div>`).join(''));
}
async function entered(){await store.membership();$('login').hidden=true;$('workspace').hidden=false;$('user-email').textContent=store.session.user.email;await sync();render();timer=setInterval(()=>{if(document.visibilityState==='visible'&&!$('modal').open&&!pollStopped)sync();},30000);}
$('login-form').onsubmit=async event=>{event.preventDefault();$('login-error').textContent='';const button=event.submitter;button.disabled=true;try{await store.login($('email').value,$('password').value);$('password').value='';await entered();}catch(e){$('login-error').textContent=e.message;}finally{button.disabled=false;}};
$('email-login').onclick=async()=>{if(!$('email').reportValidity())return;$('email-login').disabled=true;try{await store.emailLogin($('email').value,location.origin+'/');$('login-error').textContent='초대된 계정의 이메일에 로그인 링크를 보냈습니다. 이메일에서 링크를 열어주세요.';}catch(e){$('login-error').textContent=e.message;}finally{$('email-login').disabled=false;}};
$('logout').onclick=()=>{clearInterval(timer);store.logout();$('workspace').hidden=true;$('login').hidden=false;$('content').replaceChildren();$('modal').close();};
$('sync').onclick=()=>safe(async()=>{await sync();render();});
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{page=b.dataset.page;document.querySelectorAll('[data-page]').forEach(n=>n.classList.toggle('active',n===b));$('page-title').textContent=b.querySelector('span').textContent;render();});
let debounce;for(const id of ['from','to','channel','search'])$(id).addEventListener('input',()=>{clearTimeout(debounce);debounce=setTimeout(()=>safe(()=>{dateString($('from').value);dateString($('to').value);render();}),180);});
$('to').value=today();const before=new Date(today()+'T00:00:00Z');before.setUTCDate(before.getUTCDate()-6);$('from').value=before.toISOString().slice(0,10);
try{const hash=location.hash;history.replaceState(null,'',location.pathname+location.search);if(await store.acceptEmailSession(hash)){await entered();}else{const saved=sessionStorage.getItem('reqm-flow-session');if(saved){store.session=JSON.parse(saved);await entered();}}}catch(e){store.logout();$('login').hidden=false;$('workspace').hidden=true;$('login-error').textContent=e.message;}
