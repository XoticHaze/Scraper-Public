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
    return u.protocol === 'https:' && domains.includes(u.hostname) ? u.href : null;
  } catch (_) { return null; }
};
const sourceDomains = ['www.ebay.com','www.bestbuy.com','www.gsaauctions.gov','gsaauctions.gov',
  'www.govdeals.com','www.publicsurplus.com','webapp1.sanantonio.gov','web.tfc.texas.gov',
  'www.gsafleet.gov','shopgoodwill.com','www.heb.com','www.walmart.com'];
const link = (parent, href, label, domains) => {
  const safe = safeUrl(href, domains);
  if (!safe) return;
  const a = addText(parent,'a',label);
  a.href = safe;
  a.target='_blank';a.rel='noopener noreferrer';
};
const states = {
 ebay:'Adapter ready, no live API', bestbuy:'Adapter ready, no live API',
 gsa:'Official API verified; durable refresh needs a key',
 govdeals:'Discovery only; automated crawling restricted',
 publicsurplus:'Discovery only; written permission needed',
 shopgoodwill:'Discovery only; authorized access required',
 san_antonio_surplus:'Public listing, collection review pending',
 tx_state_surplus:'Referral to agency auctions',
 gsa_fleet:'Vehicle Hunt candidate; not ingested',
 heb:'Local price-feed authorization needed',
 walmart:'Localized feed authorization needed'
};
getJson('marketplace-sources.json').then(data => {
  if (data.schema !== 'scraper-marketplace-directory-v1' || !Array.isArray(data.sources)) throw new Error('invalid registry');
  byId('source-status').textContent = data.sources.length + ' registered sources. None automatically marked live.';
  for (const s of data.sources) {
    const card = document.createElement('article'); card.className='card';
    addText(card,'h3',s.name || s.id);
    addText(card,'span',String(s.priority || 'P2'),'tag');
    addText(card,'p',states[s.id] || 'Access not validated','source');
    const live = !!s.collector_enabled;
    addText(card,'p',live ? 'Collector enabled' : 'Collector disabled','source');
    link(card,s.url,'Browse official source',sourceDomains);
    sourcesRoot.appendChild(card);
  }
}).catch(() => {byId('source-status').textContent='No verified source directory published.';});
let lots=[];
const price = val => val === null || val === undefined ? 'Unknown' : '$'+Number(val).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const render = () => {
  const query=byId('gsa-query').value.toLowerCase().trim();
  const state=byId('gsa-state').value;
  gsaRoot.replaceChildren();
  const rows=lots.filter(l=>(!state || l.state===state) && (!query || (l.title+' '+l.city+' '+l.agency).toLowerCase().includes(query))).slice(0,150);
  byId('gsa-empty').textContent = rows.length ? '' : lots.length ? 'No matching auctions in this source snapshot.' : 'No verified fresh GSA auction snapshot is published yet.';
  byId('gsa-summary').textContent=lots.length ? ' · '+rows.length+' visible' : '';
  for(const l of rows) {
    const card=document.createElement('article');card.className='card';
    addText(card,'h3',l.title);
    addText(card,'p',l.city+', '+l.state,'source');
    addText(card,'p','High bid: '+price(l.current_bid));
    addText(card,'p','Close date: '+(l.closing_date || 'Unknown')+' (time not verified)','source');
    addText(card,'p','All-in cost: Unverified · Sold as-is','source');
    if(l.image_url){const src=safeUrl(l.image_url,['www.gsaauctions.gov','gsaauctions.gov','www.gsa.gov','gsa.gov']);if(src){const im=document.createElement('img');im.src=src;im.alt='';im.loading='lazy';im.style='width:100%;max-height:150px;object-fit:contain';card.prepend(im);}}
    link(card,l.url,'Official item details',['www.gsaauctions.gov','gsaauctions.gov','www.gsa.gov','gsa.gov']);
    if(!l.url)link(card,'https://gsaauctions.gov','Open GSA auction site',['gsaauctions.gov']);
    gsaRoot.appendChild(card);
  }
};
for(const id of ['gsa-query','gsa-state'])byId(id).addEventListener(id==='gsa-query'?'input':'change',render);
getJson('gsa-auctions.json').then(data=>{
  if(data.schema!=='scraper-gsa-auctions-v1'||data.source_status!=='verified_live_api_response'||!Array.isArray(data.auctions))throw Error('invalid snapshot');
  const observed=Date.parse(data.observed_at);
  if(!Number.isFinite(observed)||Date.now()-observed>86400000||observed>Date.now()+300000)throw Error('stale snapshot');
  lots=data.auctions;
  byId('gsa-health').textContent='Verified GSA API snapshot · '+lots.length+' auction lots · Observed '+new Date(observed).toLocaleString()+'. High bids are not landed prices.';
  render();
}).catch(()=>{byId('gsa-health').textContent='GSA feed not yet published or expired. The official API adapter is implemented, but a durable authorized refresh key is needed.';render();});
})();
