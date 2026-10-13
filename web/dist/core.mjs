export const pyjson = values => '[' + values.map(v => Array.isArray(v)?pyjson(v):JSON.stringify(v)).join(', ') + ']';
export const fraction = (a,b=1) => {
  a=BigInt(a);b=BigInt(b);if(b<=0n)throw Error('수량을 확인하세요.');
  let x=a<0n?-a:a,y=b;while(y){[x,y]=[y,x%y];}a/=x;b/=x;return b===1n?String(a):a+'/'+b;
};
export const scaleFraction = (value,count) => {const [a,b='1']=String(value).split('/'),n=BigInt(a)*BigInt(count),d=BigInt(b);if(n%d)throw Error('배분 금액이 원 단위 정수가 아닙니다.');const result=Number(n/d);return money(result);};
export async function priceKey(data,components,family,total){
  const q=quantity(data.quantity),parts=components.map(c=>[family(c.code),fraction(quantity(c.quantity),q)]).sort((a,b)=>a[0]<b[0]?-1:a[0]>b[0]?1:0);
  if(new Set(parts.map(p=>p[0])).size!==parts.length)return null;
  const identity=pyjson([channelName(data.channel),data.account||'',parts,fraction(money(total),q)]);
  const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(identity));return 'voucher:v1:'+Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
}
export const text = v => String(v ?? '').trim();
export const channelName = v => text(v).replace(/^리큐엠_/, '');
export const money = v => {
  const n = Number(String(v).replaceAll(',', ''));
  if (!Number.isSafeInteger(n) || n < 0) throw Error('금액은 0 이상의 원 단위 정수로 입력하세요.');
  return n;
};
export const quantity = v => {
  const n = money(v); if (!n) throw Error('수량은 1 이상의 정수여야 합니다.'); return n;
};
export const cleanName = name => text(name).replace(/^(?:(?:\[리큐엠\]|【리큐엠】)\s*|리큐엠\s*[-_:]\s*)+/, '');
export const uid = prefix => prefix + crypto.randomUUID().replaceAll('-', '');
export const dateString = value => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || new Date(value+'T00:00:00Z').toISOString().slice(0,10)!==value) throw Error('날짜를 확인하세요.');
  return value;
};
export const blobValue = bytes => {
  let s='';for(let i=0;i<bytes.length;i+=16384)s+=String.fromCharCode(...bytes.subarray(i,i+16384));
  return {__reqm_bytes__:btoa(s)};
};
export const decodeBlob = value => Uint8Array.from(atob(value.__reqm_bytes__),c=>c.charCodeAt(0));
export const mappingKey = data => pyjson([data.channel,data.account,data.product,data.option]);
export const feeKey = data => pyjson(['voucher-order',channelName(data.channel),data.account||'',data.order_no]);

export class SharedStore {
  constructor(config, fetcher=globalThis.fetch.bind(globalThis)) {
    this.config=config;this.fetcher=fetcher;this.records=new Map();this.cursor=0;this.session=null;this.refreshing=null;this.busy=false;
    this.tables=['orders','mappings','item_names','requests','request_lines','shipments','smartstore_erp_rows','esm_erp_rows','fees','settings','tracking_rows'];
  }
  async login(email,password) {
    const response=await this.fetcher(this.config.url+'/auth/v1/token?grant_type=password',{method:'POST',signal:AbortSignal.timeout(20000),headers:{apikey:this.config.key,'Content-Type':'application/json'},body:JSON.stringify({email,password})});
    if(!response.ok)throw Error('로그인에 실패했습니다. 계정과 비밀번호를 확인하세요.');
    this.session=await response.json();this.session.expires_at=Date.now()+this.session.expires_in*1000;
    sessionStorage.setItem('reqm-flow-session',JSON.stringify(this.session));
    await this.membership();
  }
  async membership() {
    const rows=await this.api('/rest/v1/flow_sync_members?select=workspace_key&workspace_key=eq.default');
    if(!rows.length){this.logout();throw Error('이 계정에는 FLOW 공유 작업공간 권한이 없습니다.');}
  }
  async emailLogin(email,redirectTo){
    const response=await this.fetcher(this.config.url+'/auth/v1/otp?redirect_to='+encodeURIComponent(redirectTo),{method:'POST',signal:AbortSignal.timeout(20000),headers:{apikey:this.config.key,'Content-Type':'application/json'},body:JSON.stringify({email,create_user:false})});
    if(!response.ok)throw Error('이메일 로그인을 요청하지 못했습니다. 초대된 이메일과 잠시 후 재시도를 확인하세요.');
  }
  async acceptEmailSession(hash){
    const values=new URLSearchParams(hash.replace(/^#/,''));
    if(!values.get('access_token'))return false;
    this.session={access_token:values.get('access_token'),refresh_token:values.get('refresh_token'),expires_at:Date.now()+Number(values.get('expires_in')||3600)*1000};
    try{this.session.user=await this.api('/auth/v1/user');await this.membership();sessionStorage.setItem('reqm-flow-session',JSON.stringify(this.session));return true;}
    catch(error){this.logout();throw error;}
  }
  logout(){this.session=null;this.records.clear();this.cursor=0;sessionStorage.removeItem('reqm-flow-session');}
  async token() {
    if(!this.session)throw Error('먼저 로그인하세요.');
    if(this.session.expires_at>Date.now()+120000)return this.session.access_token;
    if(!this.refreshing)this.refreshing=(async()=>{
      const response=await this.fetcher(this.config.url+'/auth/v1/token?grant_type=refresh_token',{method:'POST',signal:AbortSignal.timeout(20000),headers:{apikey:this.config.key,'Content-Type':'application/json'},body:JSON.stringify({refresh_token:this.session.refresh_token})});
      if(!response.ok){this.logout();throw Error('로그인이 만료되었습니다. 다시 로그인하세요.');}
      this.session=await response.json();this.session.expires_at=Date.now()+this.session.expires_in*1000;
      sessionStorage.setItem('reqm-flow-session',JSON.stringify(this.session));return this.session.access_token;
    })().finally(()=>this.refreshing=null);
    return this.refreshing;
  }
  async api(path,body) {
    const token=await this.token();
    const response=await this.fetcher(this.config.url+path,{method:body?'POST':'GET',signal:AbortSignal.timeout(20000),headers:{apikey:this.config.key,Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
    if(!response.ok){
      const error=await response.json().catch(()=>({}));
      if(response.status===402||response.status===429)throw Error('사용량 제한으로 동기화를 중단했습니다. 잠시 후 수동으로 다시 연결하세요.');
      if(text(error.message).includes('FLOW_ROW_CONFLICT'))throw Error('다른 작업자가 같은 데이터를 변경했습니다. 새로고침 후 다시 작업하세요.');
      throw Error('공유 작업 실패 ('+response.status+'). 권한 또는 연결 상태를 확인하세요.');
    }
    return response.status===204?null:response.json();
  }
  apply(rows) {
    for(const row of rows){
      if(row.deleted)this.records.delete(row.row_key);
      else this.records.set(row.row_key,row);
    }
  }
  async sync() {
    if(this.busy)return false;
    this.busy=true;
    try{
      const meta=await this.api('/rest/v1/flow_sync_meta?select=version&workspace_key=eq.default');
      const target=meta[0]?.version;
      if(target===undefined)throw Error('공유 작업공간을 찾지 못했습니다.');
      if(target===this.cursor)return false;
      const collected=[];
      for(let offset=0;;offset+=500){
        const path='/rest/v1/flow_sync_records?select=row_key,table_name,payload,deleted,revision&workspace_key=eq.default&table_name=in.('+this.tables.join(',')+')&revision=gt.'+this.cursor+'&revision=lte.'+target+'&order=row_key.asc&limit=500&offset='+offset;
        const rows=await this.api(path);collected.push(...rows);if(rows.length<500)break;
      }
      // Artifact metadata is separate: polling never downloads stored XLSX blobs.
      for(let offset=0;;offset+=500){
        const rows=await this.api('/rest/v1/flow_sync_records?select=row_key,table_name,revision,deleted,id:payload->>id,kind:payload->>kind,day:payload->>day,registered:payload->>registered&workspace_key=eq.default&table_name=eq.artifacts&revision=gt.'+this.cursor+'&revision=lte.'+target+'&order=row_key.asc&limit=500&offset='+offset);
        collected.push(...rows.map(r=>({...r,payload:{id:r.id,kind:r.kind,day:r.day,registered:Number(r.registered||0)},metadataOnly:true})));if(rows.length<500)break;
      }
      for(let offset=0;;offset+=500){
        const rows=await this.api('/rest/v1/flow_sync_records?select=row_key,table_name,revision,deleted,id:payload->>id,identity:payload->>identity,kind:payload->>kind,day:payload->>day,source_name:payload->>source_name&workspace_key=eq.default&table_name=eq.tracking_jobs&revision=gt.'+this.cursor+'&revision=lte.'+target+'&order=row_key.asc&limit=500&offset='+offset);
        collected.push(...rows.map(r=>({...r,payload:{id:r.id,identity:r.identity,kind:r.kind,day:r.day,source_name:r.source_name},metadataOnly:true})));if(rows.length<500)break;
      }
      this.apply(collected);this.cursor=target;return true;
    }finally{this.busy=false;}
  }
  rows(table){return [...this.records.values()].filter(r=>r.table_name===table).map(r=>r.payload);}
  find(table,id,key='id'){return this.rows(table).find(r=>r[key]===id);}
  record(table,id){return this.records.get(table+':'+pyjson([id]));}
  change(table,payload,id=payload.id??payload.key??payload.bundle??payload.erp_item_code??payload.name){
    const row_key=table+':'+pyjson([id]);const prior=this.records.get(row_key);
    return {row_key,table_name:table,payload,deleted:false,expected_revision:prior?.revision||0};
  }
  async commit(changes){
    if(this.busy)throw Error('동기화가 끝난 후 다시 시도하세요.');
    this.busy=true;
    try{
      const dedup=[...new Map(changes.map(c=>[c.row_key,c])).values()];
      if(new TextEncoder().encode(JSON.stringify(dedup)).length>12000000)throw Error('파일 또는 작업이 너무 큽니다. 나누어 입력하세요.');
      const result=await this.api('/rest/v1/rpc/flow_sync_apply',{p_workspace:'default',p_changes:dedup});
      // Never advance the cursor here: another worker may have committed while
      // this transaction was in flight. The next delta must include that edit.
      this.apply(dedup.map(c=>({...c,revision:result.version})));return result;
    }finally{this.busy=false;}
  }
  async loadBlob(table,id,key='id'){
    const row_key=table+':'+pyjson([id]);
    const rows=await this.api('/rest/v1/flow_sync_records?select=row_key,table_name,payload,deleted,revision&workspace_key=eq.default&row_key=eq.'+encodeURIComponent(row_key)+'&deleted=eq.false');
    if(!rows.length)throw Error('저장 파일을 찾지 못했습니다.');return rows[0].payload;
  }
}

export function voucherGroups(store,from,to) {
  const orders=new Map(store.rows('orders').map(o=>[o.id,{...o,data:JSON.parse(o.data),components:JSON.parse(o.components)}]));
  const lines=new Map(store.rows('request_lines').map(r=>[r.id,r]));const groups=new Map();
  for(const s of store.rows('shipments')){
    if(s.day<from||s.day>to)continue;
    const line=lines.get(s.line_id),order=orders.get(line?.order_id);if(!order)continue;
    const settings=store.records.get('settings:[]')?.payload||{};
    if(channelName(order.data.channel)==='스마트스토어'&&(settings.profiles||[]).some(p=>['smartstore_erp','smartstore_purchase_erp'].includes(p.purpose)&&p.enabled&&p.columns))continue;
    const id='shipment:'+order.id+':'+s.day;
    if(!groups.has(id))groups.set(id,{id,kind:'shipment',day:s.day,data:order.data,components:[],issue:'',exported:false,confirmed:true,order_id:order.id});
    const g=groups.get(id),c={...order.components[line.component],entry_id:s.id,index:line.component,quantity:s.qty,amount:s.erp_amount??'0'};
    if(s.erp_code)c.code=s.erp_code;if(s.erp_name)c.name=s.erp_name;if(s.erp_warehouse)c.warehouse=s.erp_warehouse;
    g.components.push(c);g.exported ||= !!s.erp_id;g.confirmed &&= !!s.amount_split_confirmed;
  }
  for(const [table,kind] of [['smartstore_erp_rows','smartstore'],['esm_erp_rows','esm']])for(const r of store.rows(table)){
    if(r.day<from||r.day>to)continue;
    groups.set(kind+':'+r.id,{id:kind+':'+r.id,kind,day:r.day,order_id:r.id,data:JSON.parse(r.data),components:JSON.parse(r.components).map((c,index)=>({...c,index})),issue:r.issue,exported:!!r.erp_id,confirmed:kind==='smartstore'?!!r.amount_split_confirmed:!r.issue});
  }
  return [...groups.values()];
}

export function erpPreview(store,from,to,on,options={}) {
  dateString(from);dateString(to);dateString(on);if(from>to)throw Error('출고 조회 기간을 확인하세요.');
  const groups=voucherGroups(store,from,to).filter(g=>!g.exported&&(!options.ids||options.ids.includes(g.id)));
  if(!groups.length)throw Error('선택한 기간에 새 전표로 만들 출고가 없습니다.');
  const settings=store.record('settings',undefined)?.payload||store.records.get('settings:[]')?.payload||{};
  const rows=[],changes=[],fees=new Map();
  const append=(c,q,total)=>{
    q=quantity(q);total=money(total);if(!c.code||!c.customer)throw Error('품목코드와 판매처 거래처코드를 확인하세요.');
    if(!['100','300'].includes(String(c.warehouse)))throw Error('출하창고는 100 또는 300으로 지정하세요.');
    const base=Math.floor(total/q),rest=total%q;
    for(const [count,unit] of [[q-rest,base],[rest,base+1]])if(count){const supply=Math.round(count*unit/1.1);rows.push([Number(on.replaceAll('-','')),null,c.customer,null,settings.manager_code||'00109',Number(c.warehouse),null,null,null,null,null,null,c.code,c.name,null,count,unit,null,supply,count*unit-supply,null,null]);}
  };
  for(const g of groups){
    if(g.issue||!g.components.length||!g.confirmed)throw Error('상품 매칭과 세트 금액 확인을 먼저 완료하세요: '+g.data.order_no);
    for(const c of g.components)append(c,c.quantity,c.amount);
    const key=feeKey(g.data);if(!fees.has(key))fees.set(key,[]);fees.get(key).push(g);
  }
  for(const [key,list] of fees){
    const legacy=list.map(g=>pyjson([g.data.channel,g.data.account,g.data.bundle||g.data.order_no]));
    if(store.find('fees',key,'bundle')||legacy.some(k=>store.find('fees',k,'bundle')))continue;
    const override=store.find('mappings','voucher:v1:fee:'+key,'key');
    const allData=[...store.rows('orders'),...store.rows('smartstore_erp_rows'),...store.rows('esm_erp_rows')].map(r=>JSON.parse(r.data)).filter(d=>feeKey(d)===key);
    const values=override?[money(JSON.parse(override.components)[0])]:[...list.map(g=>g.data),...allData].map(d=>money(d.shipping||0));
    const positive=[...new Set(values.filter(v=>v))];if(positive.length>1)throw Error('같은 주문번호의 배송비가 다릅니다: '+list[0].data.order_no);
    if(positive.length)append({...list[0].components[0],code:'택배운송비',name:'배송비'},1,positive[0]);
    changes.push({bundle:key});
  }
  const merged=new Map();for(const row of rows){const k=JSON.stringify([row[2],row[12],row[16],row[5]]);if(!merged.has(k))merged.set(k,[...row]);else{const r=merged.get(k);r[15]+=row[15];r[18]=Math.round(r[15]*r[16]/1.1);r[19]=r[15]*r[16]-r[18];}}
  return {groups,fees:changes,rows:[...merged.values()].sort((a,b)=>a[5]-b[5])};
}
