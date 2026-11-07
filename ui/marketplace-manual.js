(() => {
'use strict';
// Manual references only. Never fetch third-party site contents or sync this data.
const key='scraper-marketplace-manual-shortlist-v1';
const byId=id=>document.getElementById(id);
const allowed=new Set(['www.ebay.com','ebay.com','www.bestbuy.com','bestbuy.com',
 'www.gsaauctions.gov','gsaauctions.gov','www.govdeals.com','govdeals.com',
 'www.publicsurplus.com','publicsurplus.com','webapp1.sanantonio.gov',
 'web.tfc.texas.gov','www.gsafleet.gov','shopgoodwill.com','www.shopgoodwill.com',
 'www.heb.com','heb.com','www.walmart.com','walmart.com']);
const sensitive=/^(api[_-]?key|access[_-]?token|token|auth|authorization|session|password|secret|jwt)$/i;
const tracking=/^(utm_|fbclid$|gclid$|mc_cid$|mc_eid$)/i;
const cleanUrl=value=>{
  if(typeof value!=='string'||value.length>1200) return null;
  let u;
  try {u=new URL(value);}catch(_){return null;}
  if(u.protocol!=='https:'||!allowed.has(u.hostname)||u.username||u.password) return null;
  for(const k of [...u.searchParams.keys()]){
    if(sensitive.test(k)) return null;
    if(tracking.test(k)) u.searchParams.delete(k);
  }
  u.hash='';
  return u.href;
};
const text=(parent,tag,value,cls)=>{
  const el=document.createElement(tag);el.textContent=String(value==null?'':value);
  if(cls)el.className=cls;parent.appendChild(el);return el;
};
let entries=[];
try {
  const stored=JSON.parse(localStorage.getItem(key)||'[]');
  if(Array.isArray(stored)) entries=stored.filter(x=>x&&cleanUrl(x.url)===x.url&&typeof x.title==='string').slice(0,80);
} catch(_) { entries=[]; }
const status=message=>{byId('manual-status').textContent=message;};
const persist=()=>{
  try{localStorage.setItem(key,JSON.stringify(entries));return true;}
  catch(_){status('Browser storage unavailable. No entry was saved.');return false;}
};
const price=value=>value===null||value===undefined?'Not supplied':'$'+Number(value).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const render=()=>{
  const root=byId('manual-items');root.replaceChildren();
  if(!entries.length){text(root,'p','No manual listings saved yet. Paste an official item URL above or use Save on a GSA auction.','empty');return;}
  for(const entry of entries){
    const card=document.createElement('article');card.className='card';
    text(card,'h3',entry.title);
    const link=text(card,'a','Open official listing');
    link.href=entry.url;link.target='_blank';link.rel='noopener noreferrer';
    const observations=Array.isArray(entry.observations)?entry.observations:[];
    const last=observations.length?observations[observations.length-1]:null;
    text(card,'p','Last user-entered price/bid: '+price(last&&last.amount),'source');
    text(card,'p',observations.length+' manual observation(s); not a verified price history','source');
    if(entry.notes)text(card,'p',entry.notes,'source');
    text(card,'p','Saved '+(entry.saved_at||'unknown time'),'source');
    const remove=text(card,'button','Remove from this browser');
    remove.type='button';
    remove.addEventListener('click',()=>{
      const before=entries;entries=entries.filter(x=>x.url!==entry.url);
      if(!persist()) entries=before;
      else status('Local reference removed.');
      render();
    });
    root.appendChild(card);
  }
};
const add=(data)=>{
  const url=cleanUrl(data.url);
  const title=typeof data.title==='string'?data.title.trim().slice(0,120):'';
  if(!url||!title){status('Only HTTPS item links from the registered official sources can be saved. No credentials in URLs.');return false;}
  const now=new Date().toISOString();
  const rawPrice=data.price;
  const hasPrice=rawPrice!==null&&rawPrice!==undefined&&String(rawPrice).trim()!=='';
  const n=hasPrice?Number(rawPrice):null;
  if(hasPrice&&(!Number.isFinite(n)||n<0||n>=1000000000)){status('Price must be a nonnegative USD amount or blank.');return false;}
  const older=entries.find(x=>x.url===url);
  const observations=older&&Array.isArray(older.observations)?older.observations.slice(-59):[];
  if(hasPrice)observations.push({observed_at:now,amount:Math.round(n*100)/100});
  const next={url,title,notes:String(data.notes||'').slice(0,300),saved_at:now,observations};
  const previous=entries;
  entries=[next,...entries.filter(x=>x.url!==url)].slice(0,80);
  if(!persist()){entries=previous;return false;}
  status('Saved in this browser only. Prices are user-entered observations, not live verification.');
  render();return true;
};
byId('manual-form').addEventListener('submit',e=>{
  e.preventDefault();
  if(add({title:byId('manual-title').value,url:byId('manual-url').value,
          price:byId('manual-price').value,notes:byId('manual-notes').value})){
    byId('manual-form').reset();
  }
});
window.addEventListener('scraper-shortlist-add',event=>{
  if(event.detail&&add(event.detail)) byId('manual-shortlist').scrollIntoView({behavior:'smooth',block:'start'});
});
render();
})();