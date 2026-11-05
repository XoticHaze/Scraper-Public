(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const catalog = window.VEHICLE_CATALOG || {vehicles:[]};
  const history = window.VEHICLE_PRICE_HISTORY || {observations:[],continuity_status:'NOT_AVAILABLE'};
  const observations = (history.observations || []).filter(o => o && /^[A-HJ-NPR-Z0-9]{17}$/.test(String(o.vin || '')) && Number.isFinite(Number(o.price)));
  const money = n => Number.isFinite(Number(n)) ? new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(n) : '—';
  const num = n => Number.isFinite(Number(n)) ? new Intl.NumberFormat('en-US').format(n) : '—';
  const lineText = (tag, text) => {const el=document.createElement(tag);el.textContent=String(text);return el;};
  const safeLink = url => {try {const u=new URL(url);return u.protocol==='https:' ? u.href : null;} catch (_) {return null;}};
  const newest = {};
  observations.forEach(o => {const prev=newest[o.vin]; if(!prev || Date.parse(o.observed_at)>Date.parse(prev.observed_at)) newest[o.vin]=o;});
  const ranked = (catalog.vehicles||[]).filter(v=>v.vin && Number.isFinite(Number(v.price)));
  const market = (catalog.market_observations||ranked).filter(v=>v.vin && v.listing_link_status==='verified' && Number.isFinite(Number(v.price)));
  const vinRows = Array.from(new Set([...ranked.map(v=>v.vin),...Object.keys(newest)])).map(vin => {
    const row = ranked.find(v=>v.vin===vin) || newest[vin];
    return {vin,label:String(row.year||'')+' Toyota RAV4 '+String(row.trim||'')+' · '+String(vin).slice(-6)+' · '+money(row.price),price:Number(row.price),row};
  });
  const formatDate = s => {const ms=Date.parse(s);return Number.isFinite(ms)?new Date(ms).toLocaleString('en-US',{timeZone:'America/Chicago',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'Unknown';};
  const median = data => {const a=data.map(Number).filter(Number.isFinite).sort((x,y)=>x-y);if(!a.length)return null;const mid=Math.floor(a.length/2);return a.length%2?a[mid]:(a[mid-1]+a[mid])/2;};
  const distinctDealers = new Set(ranked.map(v=>v.dealer||v.source||'unknown'));
  $('kpi-listings').textContent=num(ranked.length);
  $('kpi-dealers').textContent=num(distinctDealers.size);
  $('kpi-points').textContent=num(observations.length);
  $('kpi-market').textContent=num(new Set(market.map(v=>v.vin)).size);
  $('market-meta').textContent=String(catalog.generated_utc||'no live catalog').replace('T',' ').slice(0,19)+' UTC · Historical asking observations only';
  const warnings=[];
  if(ranked.length && distinctDealers.size===1) warnings.push('All '+ranked.length+' current ranked cars come from ONE dealership. This is not a representative San Antonio RAV4 market.');
  if(!ranked.some(v=>Number(v.mileage)<=35000)) warnings.push('No current ranked match meets the ≤35,000-mile goal.');
  const times=observations.map(o=>Date.parse(o.observed_at)).filter(Number.isFinite);
  if(times.length<2 || Math.max(...times)-Math.min(...times)<86400000) warnings.push('History covers less than a day. It cannot establish whether market prices are increasing.');
  if(history.continuity_status!=='PUBLISHED_HISTORY_READ') warnings.push('History continuity is limited to verified seed/last-catalog observations until the previous published history is retrieved.');
  $('coverage-alert').textContent=warnings.join(' ')||'Dealer breadth and historical observations are available. Verify the sample before drawing a trend conclusion.';

  const svgNS='http://www.w3.org/2000/svg';
  function shape(kind, attrs, text) {
    const n=document.createElementNS(svgNS,kind);
    Object.entries(attrs||{}).forEach(([key,value])=>n.setAttribute(key,String(value)));
    if(text!==undefined)n.textContent=String(text);
    return n;
  }
  const seriesFor = vin => observations.filter(o=>o.vin===vin).sort((a,b)=>Date.parse(a.observed_at)-Date.parse(b.observed_at));
  function plot(vin) {
    const list=seriesFor(vin), svg=$('price-history-chart');
    svg.replaceChildren();$('history-rows').replaceChildren();
    if(!list.length) {$('history-summary').textContent='No historical scan observations are available for this VIN.';return;}
    const old=list[0],last=list[list.length-1],delta=last.price-old.price;
    $('history-summary').textContent=list.length+' observed scans · '+money(old.price)+' → '+money(last.price)+' · '+(delta>0?'+':'')+money(delta)+' overall, '+formatDate(old.observed_at)+' through '+formatDate(last.observed_at)+'.';
    const minT=Math.min(...list.map(o=>Date.parse(o.observed_at))),maxT=Math.max(...list.map(o=>Date.parse(o.observed_at)));
    const minP=Math.min(...list.map(o=>Number(o.price))),maxP=Math.max(...list.map(o=>Number(o.price)));
    const pSpan=Math.max(200,maxP-minP);
    const left=90,right=890,top=32,bottom=244;
    const scaleX=t=>left+(right-left)*((t-minT)/(maxT-minT||1));
    const scaleY=p=>bottom-(bottom-top)*((p-(minP-pSpan*.2))/(pSpan*1.4));
    for(let i=0;i<=4;i++){
      const y=bottom-(bottom-top)*i/4; const price=(minP-pSpan*.2)+(pSpan*1.4)*i/4;
      svg.appendChild(shape('line',{x1:left,y1:y,x2:right,y2:y,stroke:'#304255','stroke-width':1}));
      svg.appendChild(shape('text',{x:78,y:y+5,fill:'#b5c9dd','text-anchor':'end','font-size':14},money(price)));
    }
    const points=list.map(o=>scaleX(Date.parse(o.observed_at))+','+scaleY(Number(o.price))).join(' ');
    // A single observation is a point, not a price trend.
    if (list.length > 1) {
      svg.appendChild(shape('polyline',{points,fill:'none',stroke:'#76c7ec','stroke-width':3,'stroke-linecap':'round','stroke-linejoin':'round'}));
    }
    list.forEach(o=>svg.appendChild(shape('circle',{cx:scaleX(Date.parse(o.observed_at)),cy:scaleY(Number(o.price)),r:5,fill:'#a1e9ff',stroke:'#142536','stroke-width':2})));
    svg.appendChild(shape('text',{x:left,y:277,fill:'#b5c9dd','font-size':14},formatDate(list[0].observed_at)));
    svg.appendChild(shape('text',{x:right,y:277,fill:'#b5c9dd','font-size':14,'text-anchor':'end'},formatDate(last.observed_at)));
    if(minT===maxT)svg.appendChild(shape('text',{x:470,y:165,fill:'#d5e7f7','text-anchor':'middle','font-size':18},'Single actual observation; no trend yet'));
    list.slice().reverse().forEach((o,i,reverse)=>{
      const previous = reverse[reverse.length-i-2],tr=document.createElement('tr');
      const change=previous ? Number(o.price)-Number(previous.price) : null;
      [formatDate(o.observed_at),money(o.price),change===null?'First observed':(change>0?'+':'')+money(change),String(o.snapshot_ref||o.source||'Public scan')].forEach(v=>tr.appendChild(lineText('td',v)));
      $('history-rows').appendChild(tr);
    });
  }

  function fillSelect(id) {
    const select=$(id);select.replaceChildren();
    vinRows.forEach(v=>{const opt=document.createElement('option');opt.value=v.vin;opt.textContent=v.label;select.appendChild(opt);});
    if(!vinRows.length){const opt=document.createElement('option');opt.value='';opt.textContent='No verified VINs';select.appendChild(opt);}
  }
  fillSelect('vin-select');fillSelect('finance-vehicle');
  const requested=new URLSearchParams(location.search).get('vin');
  if(vinRows.some(v=>v.vin===requested)){$('vin-select').value=requested;$('finance-vehicle').value=requested;}
  $('vin-select').addEventListener('change',()=>plot($('vin-select').value));
  plot($('vin-select').value);
  $('history-continuity').textContent='Continuity: '+history.continuity_status+' · First stored observation '+(history.first_observed_utc?formatDate(history.first_observed_utc):'none')+'. Asking prices, not sale transactions; a flat short series is not evidence the broader market is flat.';

  const grouped={};
  market.forEach(v=>{const key=String(v.dealer||v.source||'Unknown')+'|'+String(v.location||'Unspecified');(grouped[key]||(grouped[key]=[])).push(v);});
  $('dealer-rows').replaceChildren();
  Object.entries(grouped).sort((a,b)=>b[1].length-a[1].length).forEach(([key,rows])=>{
    const tr=document.createElement('tr');
    const values=[key.replace('|',' · '),new Set(rows.map(v=>v.vin)).size,money(median(rows.map(v=>v.price))),num(median(rows.map(v=>v.mileage)))+' mi',rows.filter(v=>Number(v.price)<=27000).length];
    values.forEach(v=>tr.appendChild(lineText('td',v)));$('dealer-rows').appendChild(tr);
  });
  $('dealer-footnote').textContent=Object.keys(grouped).length+' distinct dealer/area groups in the broader observed sample. Filtered ranked results: '+distinctDealers.size+' sellers. Source HTTP 403 errors and missing detail pages create selection bias; do not call the sample market representative.';

  const inputs=['offer-price','apr','term','down','trade','payoff','addons','doc','title-fee','insurance','fuel','upkeep','monthly-budget'];
  const n=id=>Math.max(0,Number($(id).value)||0);
  const monthly = (principal,apr,term) => {
    if(principal<=0)return 0;
    const rate=apr/1200;
    return rate===0?principal/term:principal*rate/(1-Math.pow(1+rate,-term));
  };
  function evaluate(price) {
    const tax = .0625*Math.max(0,price-n('trade'));
    const otd=price+tax+n('doc')+n('addons')+n('title-fee');
    const financed=Math.max(0,otd-n('down')-n('trade')+n('payoff'));
    const payment=monthly(financed,n('apr'),n('term'));
    return {otd,financed,payment,interest:Math.max(0,payment*n('term')-financed),allin:payment+n('insurance')+n('fuel')+n('upkeep')};
  }
  function updateFinance() {
    const price=n('offer-price'),v=evaluate(price);
    $('out-otd').textContent=money(v.otd);
    $('out-financed').textContent=money(v.financed);
    $('out-payment').textContent=money(v.payment);
    $('out-allin').textContent=money(v.allin);
    $('out-interest').textContent=money(v.interest);
    let lo=0,hi=150000;
    for(let j=0;j<45;j++){const mid=(lo+hi)/2;if(evaluate(mid).allin<=n('monthly-budget'))lo=mid;else hi=mid;}
    const max=Math.floor(lo/50)*50;
    $('out-maxprice').textContent=n('monthly-budget')<=n('insurance')+n('fuel')+n('upkeep')?'No positive offer':money(max);
    const diff=max-price;
    $('scenario-note').textContent='Illustrative payment '+money(v.payment)+'/month; total including insurance, fuel and maintenance '+money(v.allin)+'/month. '+(diff>=0?'Selected price is within your estimated affordability ceiling.':'Selected price exceeds your estimated affordability ceiling by about '+money(-diff)+'.')+' Actual loan APR, insurer premium and dealer charges may materially differ.';
  }
  function vehicleFinanceChange(){
    const v=vinRows.find(x=>x.vin===$('finance-vehicle').value);
    if(!v)return;
    $('offer-price').value=v.price;
    const dealerDoc=Number(v.row.incremental_doc_fee);
    if(Number.isFinite(dealerDoc))$('doc').value=dealerDoc;
    else $('doc').value=v.row.dealer_doc_fee_included_in_price?0:Number(v.row.dealer_doc_fee)||225;
    $('addons').value=Math.max(0,Number(v.row.dealer_mandatory_addon_amount)||0);
    updateFinance();
  }
  $('finance-vehicle').addEventListener('change',vehicleFinanceChange);
  inputs.forEach(id=>$(id).addEventListener('input',updateFinance));
  document.querySelectorAll('[data-apr]').forEach(b=>b.addEventListener('click',()=>{$('apr').value=b.dataset.apr;updateFinance();}));
  vehicleFinanceChange();
})();