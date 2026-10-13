import test from 'node:test';
import assert from 'node:assert/strict';
import {SharedStore,pyjson,priceKey,fraction,scaleFraction,erpPreview,cleanName} from '../dist/core.mjs';

const response=value=>({ok:true,status:200,json:async()=>value});
globalThis.sessionStorage={setItem(){},removeItem(){}};
function store(){const s=new SharedStore({url:'https://example.invalid',key:'public'});s.session={access_token:'test',expires_at:Date.now()+3600000};return s;}
function seed(s,table,payload){const r=s.change(table,payload);s.apply([{...r,revision:1}]);}

test('Python-compatible keys, exact fraction scale and brand prefix',async()=>{
  assert.equal(pyjson(['a',['b','c']]),'["a", ["b", "c"]]');
  assert.equal(fraction(6900,2),'3450');assert.equal(fraction(1,2),'1/2');
  assert.equal(scaleFraction('1/2',2),1);assert.throws(()=>scaleFraction('1/2',1));
  assert.equal(cleanName('[리큐엠] QP2000C 블랙'),'QP2000C 블랙');
  const data={channel:'오늘의집',account:'worker',quantity:1},cs=[{code:'A',quantity:1},{code:'B',quantity:1}];
  const first=await priceKey(data,cs,c=>'model:'+c,34900);
  const second=await priceKey({...data,quantity:2},cs.map(c=>({...c,quantity:2})),c=>'model:'+c,69800);
  assert.equal(first,second);assert.notEqual(first,await priceKey(data,cs,c=>'model:'+c,33900));
});

test('Unchanged version fetches only tiny metadata; no spreadsheet blobs on sync',async()=>{
  const s=store(),paths=[];s.cursor=3;s.fetcher=async(url)=>{paths.push(url);return response([{version:3}]);};
  assert.equal(await s.sync(),false);assert.equal(paths.length,1);
  s.cursor=0;s.fetcher=async(url)=>{paths.push(url);return response(url.includes('flow_sync_meta')?[{version:3}]:[]);};
  await s.sync();assert.equal(s.cursor,3);
  const full=paths.find(p=>p.includes('table_name=in.'));
  assert.ok(!full.includes('source_files')&&!full.includes('artifacts')&&!full.includes('tracking_jobs'));
  assert.ok(paths.some(p=>p.includes('id:payload->>id')));
});

test('RPC conflict preserves local rows, failed save never marks ERP',async()=>{
  const s=store();seed(s,'orders',{id:'O',state:'출고 준비'});
  s.fetcher=async()=>({ok:false,status:400,json:async()=>({message:'FLOW_ROW_CONFLICT'})});
  await assert.rejects(s.commit([s.change('orders',{id:'O',state:'출고 요청'})]),/다른 작업자/);
  assert.equal(s.find('orders','O').state,'출고 준비');assert.equal(s.busy,false);
});

test('Write does not advance cursor past another worker update',async()=>{
  const s=store();s.cursor=4;s.fetcher=async()=>response({version:6});
  await s.commit([s.change('orders',{id:'O',state:'출고 요청'})]);
  assert.equal(s.cursor,4);assert.equal(s.record('orders','O').revision,6);
});

test('One refresh in flight and no retry password loop',async()=>{
  const s=store();s.session.expires_at=0;s.session.refresh_token='refresh';let count=0;
  s.fetcher=async()=>{count++;await new Promise(r=>setTimeout(r,5));return response({access_token:'renewed',expires_in:3600});};
  assert.deepEqual(await Promise.all([s.token(),s.token()]),['renewed','renewed']);assert.equal(count,1);
  s.session.expires_at=0;s.fetcher=async()=>({ok:false});
  await assert.rejects(s.token(),/다시 로그인/);assert.equal(s.session,null);
});

test('Email login requests an invited account without creating users',async()=>{
  const s=store();let call;
  s.fetcher=async(url,options)=>{call={url,options};return response({});};
  await s.emailLogin('worker@example.com','https://flow.example/');
  assert.match(call.url,/\/auth\/v1\/otp\?redirect_to=https%3A%2F%2Fflow\.example%2F/);
  assert.deepEqual(JSON.parse(call.options.body),{email:'worker@example.com',create_user:false});
});

test('Email link session verifies the user and workspace before saving',async()=>{
  const s=store();const paths=[];
  s.api=async path=>{paths.push(path);return path==='/auth/v1/user'?{email:'worker@example.com'}:[{workspace_key:'default'}];};
  assert.equal(await s.acceptEmailSession('#access_token=mail-token&refresh_token=refresh&expires_in=3600'),true);
  assert.equal(s.session.user.email,'worker@example.com');
  assert.deepEqual(paths,['/auth/v1/user','/rest/v1/flow_sync_members?select=workspace_key&workspace_key=eq.default']);
});

function voucherFixture(){const s=store();
  const d={channel:'오늘의집',account:'worker',order_no:'ORDER',quantity:'1',amount:'34900',shipping:'3000',recipient:'가상 수령인'};
  const cs=[{code:'BATTERY',name:'배터리 블랙',quantity:1,amount:'28000',customer:'C',warehouse:'300'},{code:'CABLE',name:'케이블 핑크',quantity:1,amount:'6900',customer:'C',warehouse:'300'}];
  seed(s,'orders',{id:'O',data:JSON.stringify(d),components:JSON.stringify(cs),state:'출고 완료'});
  for(let i=0;i<2;i++){seed(s,'request_lines',{id:'L'+i,order_id:'O',component:i});seed(s,'shipments',{id:'S'+i,line_id:'L'+i,qty:1,day:'2026-10-13',erp_amount:cs[i].amount,amount_split_confirmed:1,erp_id:null});}
  return s;
}
test('ERP preview exact totals, item names, date and one delivery fee; read only',()=>{
  const s=voucherFixture(),before=JSON.stringify([...s.records]);
  const result=erpPreview(s,'2026-10-13','2026-10-13','2026-10-14');
  assert.equal(result.rows.reduce((a,r)=>a+r[15]*r[16],0),37900);
  assert.equal(result.rows.filter(r=>r[12]==='택배운송비').length,1);
  assert.ok(result.rows.every(r=>r[0]===20261014&&r[13]));assert.equal(JSON.stringify([...s.records]),before);
  seed(s,'fees',{bundle:result.fees[0].bundle,erp_id:'OLD'});
  assert.equal(erpPreview(s,'2026-10-13','2026-10-13','2026-10-14').rows.reduce((a,r)=>a+r[15]*r[16],0),34900);
});
test('ERP rejects unconfirmed split and unsafe unit amount',()=>{
  const s=voucherFixture();seed(s,'shipments',{...s.find('shipments','S0'),amount_split_confirmed:0});
  assert.throws(()=>erpPreview(s,'2026-10-13','2026-10-13','2026-10-13'),/먼저 완료/);
});
