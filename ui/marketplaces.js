(() => {
'use strict';
const byId = id => document.getElementById(id);
const sourcesRoot = byId('sources'), gsaRoot = byId('gsa-items');
const getJson = async url => {
  const response = await fetch(url, {cache:'no-store'});
  if (!response.ok) throw new Error('not published');
  return response.json();
};
const addText = (parent, tag, value, cls) => {
  const node = document.createElement(tag);
  node.textContent = String(value == null ? '' : value);
  if (cls) node.className = cls;
  parent.appendChild(node);
  return node;
};
const safeUrl = (url, domains) => {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && !u.username && !u.password && domains.includes(u.hostname) ? u.href : null;
  } catch (_) { return null; }
};
const sourceDomains = ['www.ebay.com','ebay.com','www.bestbuy.com','bestbuy.com','www.gsaauctions.gov','gsaauctions.gov',
  'www.govdeals.com','govdeals.com','www.publicsurplus.com','publicsurplus.com',
  'webapp1.sanantonio.gov','web.tfc.texas.gov','www.gsafleet.gov','shopgoodwill.com',
  'www.shopgoodwill.com','www.heb.com','www.walmart.com'];
const gsaDomains = ['www.gsaauctions.gov','gsaauctions.gov','www.gsa.gov','gsa.gov'];
const link = (parent, href, label, domains) => {
  const safe = safeUrl(href, domains);
  if (!safe) return;
  const a = addText(parent,'a',label);
  a.href = safe; a.target='_blank'; a.rel='noopener noreferrer';
};
const states = {
 ebay:'Adapter ready, no live API', bestbuy:'Adapter ready, no live API',
 gsa:'Official API verified; recurring refresh requires a personal key',
 govdeals:'Discovery only; automated crawling restricted',
 publicsurplus:'Discovery only; written permission needed',
 shopgoodwill:'Discovery only; authorized access required',
 san_antonio_surplus:'Public listing; automation review pending',
 tx_state_surplus:'Referral to agency auctions',
 gsa_fleet:'Vehicle Hunt candidate; not ingested',
 heb:'Local price-feed authorization needed',
 walmart:'Localized feed authorization needed'
};
getJson('marketplace-sources.json').then(data => {
  if (data.schema !== 'scraper-marketplace-directory-v1' || !Array.isArray(data.sources)) throw new Error('invalid registry');
  byId('source-status').textContent = data.sources.length + ' registered sources. Registration is not a live-feed claim.';
  for (const s of data.sources) {
    const card = document.createElement('article'); card.className='card';
    addText(card,'h3',s.name || s.id);
    addText(card,'span',String(s.priority || 'P2'),'tag');
    addText(card,'p',states[s.id] || 'Access not validated','source');
    addText(card,'p',s.collector_enabled ? 'Collector enabled' : 'Collector not enabled in source registry','source');
    if (s.next_step) addText(card,'p','Next: '+s.next_step,'source');
    link(card,s.url,'Browse official source',sourceDomains);
    sourcesRoot.appendChild(card);
  }
}).catch(() => {byId('source-status').textContent='No verified source directory published.';});
const focusPatterns = {
 power:/\b(ups|uninterruptible|battery|batteries|inverter|generator|solar|power supply|power station)\b/i,
 smart:/\b(zigbee|z-wave|smart home|home automation|security camera|surveillance|nvr|doorbell|ptz|thermostat)\b/i,
 network:/\b(server|servers|network|networking|router|switches|switch|rack|nas|firewall|data center)\b/i,
 music:/\b(synthesizer|synth|piano|digital piano|musical instrument|drum machine|midi|keyboard instrument|yamaha keyboard)\b/i,
 vehicles:/\b(vehicle|truck|automobile|suv|sedan|pickup|van|trailer|automotive|car)\b/i,
 tech:/\b(computer|laptop|desktop|monitor|display|tablet|workstation|printer|electronics)\b/i
};
let lots=[];
const price = val => val === null || val === undefined || !Number.isFinite(Number(val))
  ? 'Unknown' : '$'+Number(val).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const isLocal = lot => /\bsan antonio\b/i.test(String(lot.city || ''));
const sortDate = lot => /^\d{4}-\d{2}-\d{2}$/.test(lot.closing_date || '') ? lot.closing_date : '9999-12-31';
const sortBid = lot => lot.current_bid === null || lot.current_bid === undefined ? Infinity : Number(lot.current_bid);
const sortLots = (a,b,method) => {
  if (method === 'local') {
    const priority = Number(isLocal(b))-Number(isLocal(a));
    if (priority) return priority;
  }
  if (method === 'bid') {
    const aBid=sortBid(a), bBid=sortBid(b);
    if (aBid !== bBid) return aBid-bBid;
  }
  return sortDate(a).localeCompare(sortDate(b)) || String(a.title).localeCompare(String(b.title));
};
const render = () => {
  const query=byId('gsa-query').value.toLowerCase().trim();
  const state=byId('gsa-state').value, focus=byId('gsa-focus').value, method=byId('gsa-sort').value;
  const ceilingText=byId('gsa-max-bid').value.trim();
  const ceiling=ceilingText === '' ? null : Number(ceilingText);
  gsaRoot.replaceChildren();
  const matched=lots.filter(l => {
    if (state && l.state!==state) return false;
    if (query && !(String(l.title||'')+' '+String(l.city||'')+' '+String(l.agency||'')+' '+String(l.sale_number||'')).toLowerCase().includes(query)) return false;
    if (focus && !(focusPatterns[focus] || /$^/).test(l.title||'')) return false;
    if (ceiling!==null && Number.isFinite(ceiling) && (l.current_bid===null || l.current_bid===undefined || Number(l.current_bid)>ceiling)) return false;
    return true;
  }).sort((a,b)=>sortLots(a,b,method));
  const rows=matched.slice(0,150);
  byId('gsa-empty').textContent = matched.length ? (matched.length>rows.length ? 'Showing the first '+rows.length+' of '+matched.length+' matching lots. Narrow your filters to see more.' : '') :
    lots.length ? 'No matching auctions in this source snapshot. Clear filters to widen the hunt.' : 'No verified fresh GSA auction snapshot is published yet.';
  byId('gsa-summary').textContent=lots.length ? ' · '+matched.length+' matching of '+lots.length+' total' : '';
  for(const l of rows) {
    const card=document.createElement('article');card.className='card';
    addText(card,'h3',l.title);
    addText(card,'p',(l.city||'Location not supplied')+(l.state?', '+l.state:''),'source');
    addText(card,'p','Observed high bid: '+price(l.current_bid));
    addText(card,'p','Close date: '+(l.closing_date || 'Unknown')+' (exact time not verified)','source');
    addText(card,'p','All-in cost: Unknown · No verified max bid · As-is','source');
    if(l.image_url){const src=safeUrl(l.image_url,gsaDomains);if(src){const im=document.createElement('img');im.src=src;im.alt='Auction item photo';im.loading='lazy';im.style='width:100%;max-height:180px;object-fit:contain';card.prepend(im);}}
    link(card,l.url,'Open verified GSA item link',gsaDomains);
    if(!l.url)link(card,'https://gsaauctions.gov','Browse GSA website',['gsaauctions.gov']);
    if(l.url && safeUrl(l.url,gsaDomains)){
      const save=addText(card,'button','Save to my shortlist');
      save.type='button';
      save.addEventListener('click',()=>{
        window.dispatchEvent(new CustomEvent('scraper-shortlist-add',{detail:{title:l.title,url:l.url,price:l.current_bid,notes:'GSA auction '+l.sale_number+'/'+l.lot_number+'; verify closing time, pickup and fees.'}}));
        save.textContent='Sent to local shortlist';
      });
    }
    gsaRoot.appendChild(card);
  }
};
for(const id of ['gsa-query','gsa-state','gsa-focus','gsa-sort','gsa-max-bid']) {
  byId(id).addEventListener(['gsa-query','gsa-max-bid'].includes(id)?'input':'change',render);
}
getJson('gsa-auctions.json').then(data=>{
  if(data.schema!=='scraper-gsa-auctions-v1'||data.source!=='gsa'||data.source_status!=='verified_live_api_response'||!Array.isArray(data.auctions)||data.count!==data.auctions.length) throw Error('invalid snapshot');
  const observed=Date.parse(data.observed_at);
  if(!Number.isFinite(observed)||Date.now()-observed>86400000||observed>Date.now()+300000)throw Error('stale snapshot');
  lots=data.auctions.filter(l=>l && l.source==='gsa' && l.auction_status==='active');
  if (data.filter_state==='TX') {
    byId('gsa-state').querySelector('option[value=""]').remove();
    byId('gsa-state').options[0].textContent='Texas (published source scope)';
  }
  byId('gsa-health').textContent='Verified official GSA API snapshot · '+lots.length+' active lots · Observed '+new Date(observed).toLocaleString()+'. Bids are not total prices.';
  render();
}).catch(()=>{byId('gsa-health').textContent='GSA feed not published or expired. A personal GSA API key is needed for recurring authorized refresh; other source links and your local shortlist remain usable.';render();});
})();