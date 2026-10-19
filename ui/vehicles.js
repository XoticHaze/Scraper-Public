(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const money = n => Number.isFinite(Number(n)) && n != null
    ? new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',maximumFractionDigits:0}).format(Number(n))
    : 'Not provided';
  const number = n => Number.isFinite(Number(n)) && n != null
    ? new Intl.NumberFormat('en-US').format(Number(n)) : 'Unknown';
  const node = (tag, className, value) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (value !== undefined && value !== null) el.textContent = String(value);
    return el;
  };
  const safeURL = value => { try {
    const url = new URL(String(value || ''));
    return url.protocol === 'https:' ? url.href : null;
  } catch (_) { return null; } };
  const drive = value => {
    const s = String(value || '').trim().toLowerCase();
    if (/^(all[- ]wheel drive|awd|4wd|4x4|four[- ]wheel drive)$/.test(s)) return 'AWD';
    if (/^(front[- ]wheel drive|fwd|2wd|4x2)$/.test(s)) return 'FWD';
    return 'Not confirmed';
  };
  const vehicleName = v => {
    const prefix = [v.year,v.make || 'Toyota',v.model || 'RAV4'].filter(Boolean).join(' ');
    const raw = String(v.trim || '').trim();
    if (raw && raw.length < 45 && !/for sale|used vehicles|location|tags|san antonio/i.test(raw)) return prefix + ' ' + raw;
    const match = String(v.title || '').match(/20\d{2}\s+Toyota\s+RAV4(?:\s+(?:Hybrid|Prime|LE|XLE|XSE|Limited|SE|Adventure|TRD|Woodland|Premium|AWD|FWD)){0,4})/i);
    return match ? match[0] : prefix;
  };
  const isAWD = v => drive(v.drivetrain) === 'AWD';
  const isPhoto = v => Boolean(safeURL(v.image_url)) && (
    v.photo_status === 'vehicle_specific' || /dealer_detail_gallery|dealer_detail_vehicle_photo/.test(String(v.image_source || ''))
  );
  let catalog = null;

  function link(label, url, cls) {
    const href = safeURL(url);
    if (!href) return null;
    const a = node('a', cls || '', label);
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    return a;
  }
  function field(label, value, major) {
    const div = node('div', major ? 'field major' : 'field');
    div.append(node('span','field-label',label), node('strong','field-value',value));
    return div;
  }
  function badge(label, cls) { return node('span','badge '+(cls||''),label); }

  function card(v) {
    const el = node('article','card');
    const figure = node('div','photo');
    const placeholder = node('div','photo-placeholder','Vehicle-specific image not supplied');
    const imgSrc = isPhoto(v) ? safeURL(v.image_url) : null;
    if (imgSrc) {
      const img = document.createElement('img');
      img.loading = 'lazy';
      img.alt = vehicleName(v) + ' · dealer listing photo';
      img.src = imgSrc;
      img.addEventListener('error', () => {
        figure.replaceChildren(placeholder);
        figure.classList.add('no-photo');
      }, {once:true});
      figure.appendChild(img);
    } else {
      figure.appendChild(placeholder);
      figure.classList.add('no-photo');
    }
    const figBadges = node('div','photo-flags');
    if (Number(v.mileage) <= 35000) figBadges.appendChild(badge('Preferred mileage','preferred'));
    if (isAWD(v)) figBadges.appendChild(badge('AWD','preferred'));
    if (v.certified) figBadges.appendChild(badge('Dealer CPO'));
    figure.appendChild(figBadges);
    el.appendChild(figure);

    const body = node('div','card-body');
    const header = node('div','card-head');
    const title = node('div','');
    title.appendChild(node('h3','',vehicleName(v)));
    title.appendChild(node('p','dealer',[v.dealer,v.location].filter(Boolean).join(' · ') || 'Dealer not confirmed'));
    const mainPrice = node('div','price-top');
    mainPrice.appendChild(node('strong','asking',money(v.price)));
    mainPrice.appendChild(node('span','price-caption','Asking price'));
    header.append(title,mainPrice);
    body.appendChild(header);

    const metrics = node('div','metrics');
    metrics.append(
      field('Estimated out-the-door',money(v.estimated_otd),true),
      field('Mileage',number(v.mileage)+' mi',true),
      field('Drivetrain',drive(v.drivetrain)),
      field('Location',v.locality ? String(v.locality).replaceAll('_',' ') : 'Unknown'),
      field('Vs. local listings',v.market_delta_pct == null ? 'Insufficient comps' : ((Number(v.market_delta_pct) > 0 ? '+' : '')+v.market_delta_pct+'%')),
      field('Price change',v.price_delta == null ? 'No history' : (Number(v.price_delta) === 0 ? 'Unchanged' : money(v.price_delta))),
    );
    body.appendChild(metrics);
    const chips = node('div','chips');
    if (v.listing_link_status === 'verified') chips.appendChild(badge('VIN seen on dealer detail','verified'));
    else chips.appendChild(badge('Discovery · URL unverified','pending'));
    if (Number(v.mileage)>45000) chips.appendChild(badge('Above preferred mileage','risk'));
    if (v.dealer_mandatory_addon_amount>0) chips.appendChild(badge('Dealer add-ons','risk'));
    body.appendChild(chips);
    const facts=node('p','vehicle-facts');
    facts.textContent = [
      v.vin ? 'VIN '+v.vin : 'VIN not established',
      v.fuel_type ? String(v.fuel_type) : null,
      v.transmission ? String(v.transmission) : null,
      v.stock_number ? 'Stock '+v.stock_number : null,
    ].filter(Boolean).join(' · ');
    body.appendChild(facts);
    if(v.dealer_addon_warning) body.appendChild(node('p','risk-note',v.dealer_addon_warning));
    const links = node('div','card-actions');
    if(v.listing_link_status === 'verified') {
      const a=link('Open VIN-linked vehicle ↗',v.source_url,'primary');
      if(a) links.appendChild(a);
    } else links.appendChild(node('span','unverified','Vehicle detail link is not verified'));
    if(links.children.length) body.appendChild(links);
    const more=node('details','more');
    more.appendChild(node('summary','', 'Why ranked here · fees and risks'));
    const contents=node('div','more-inner');
    contents.appendChild(node('p','',[
      ...(v.reasons||[]).map(x=>'✓ '+String(x).replaceAll('_',' ')),
      ...(v.risks||[]).map(x=>'⚠ '+String(x).replaceAll('_',' ')),
    ].join(' · ') || 'No independent valuation evidence yet.'));
    contents.appendChild(node('p','', 'Out-the-door is an estimate, not a dealer quote. Tax, title, documentary fees, and dealer packages require confirmation.'));
    more.appendChild(contents);
    body.appendChild(more);
    el.appendChild(body);
    return el;
  }

  function nearby(v, maxDistance, localOnly) {
    const distance=v.distance_miles == null ? null : Number(v.distance_miles);
    if(distance != null && Number.isFinite(distance)) return distance <= maxDistance && (!localOnly || distance <= 50);
    const label=String(v.locality||'').toLowerCase();
    return !localOnly ? label !== 'out_of_scope' : ['local','nearby'].includes(label);
  }

  function render() {
    if(!catalog)return;
    const maxPrice=Number($('max-price').value) || Infinity;
    const maxMileage=Number($('max-mileage').value) || Infinity;
    const maxDistance=Number($('max-distance').value) || Infinity;
    const localOnly=$('local').checked, awdOnly=$('awd').checked;
    const rows=(catalog.vehicles||[]).filter(v=>
      Number(v.price)<=maxPrice && Number(v.mileage)<=maxMileage
      && nearby(v,maxDistance,localOnly) && (!awdOnly||isAWD(v))
    );
    if($('sort').value==='price') rows.sort((a,b)=>a.price-b.price);
    if($('sort').value==='mileage') rows.sort((a,b)=>a.mileage-b.mileage);
    if($('sort').value==='otd') rows.sort((a,b)=>a.estimated_otd-b.estimated_otd);
    if($('sort').value==='fit') rows.sort((a,b)=>(b.deal_score||0)-(a.deal_score||0));
    $('count').textContent=number(rows.length);
    $('empty-state').hidden=rows.length>0;
    if(!rows.length){
      $('empty-description').textContent= (catalog.vehicles||[]).length
        ? 'There are '+(catalog.vehicles||[]).length+' observed vehicles, but none pass these buying filters. Broaden mileage only if you want to consider the maintenance tradeoff.'
        : 'No usable dealer listing has been confirmed. Use the dealer inventory/search links below; do not treat search result cards as verified inventory.';
    }
    $('grid').replaceChildren(...rows.map(card));
  }

  function coverage() {
    const observed=catalog.source_observations||{},errors=catalog.source_errors||{};
    $('source-status').textContent=
      Object.entries(observed).map(([k,v])=>k+': '+v).join(' · ') || 'No dealer results captured';
    if(Object.keys(errors).length) $('source-status').textContent += ' · degraded: '+Object.keys(errors).join(', ');
    for(const key of ['source-links','discovery-links']) $(key).replaceChildren();
    for(const s of (catalog.source_registry||[])){
      const a=link([s.name||s.id,s.location].filter(Boolean).join(' · '),s.inventory_url);
      if(a) $('source-links').appendChild(a);
    }
    for(const s of (catalog.discovery_routes||[])){
      const a=link(s.label||s.id,s.url);
      if(a){if(s.warning)a.title=s.warning;$('discovery-links').appendChild(a)}
    }
  }

  async function load() {
    try {
      catalog=window.VEHICLE_CATALOG||null;
      if(!catalog){
        const response=await fetch('vehicle_catalog.json?t='+Date.now(),{cache:'no-store'});
        if(!response.ok) throw new Error('HTTP '+response.status);
        catalog=await response.json();
      }
      if(!Array.isArray(catalog.vehicles)) throw new Error('No vehicle catalog schema');
      const rows=catalog.vehicles;
      $('total').textContent=number(rows.filter(v=>v.listing_link_status==='verified').length);
      $('preferred-count').textContent=number(rows.filter(v=>Number(v.mileage)<=35000).length);
      $('awd-count').textContent=number(rows.filter(isAWD).length);
      $('photo-count').textContent=number(rows.filter(isPhoto).length);
      const date=Date.parse(catalog.generated_utc);
      const age=Number.isFinite(date)?(Date.now()-date)/3600000:Infinity;
      $('meta').textContent= Number(catalog.generated_epoch_utc)>0
        ? (age>6?'STALE SNAPSHOT · ':'')+rows.length+' VIN-linked dealer observations · updated '+new Date(date).toLocaleString('en-US')+
          ' · photos and listed details are dealer-sourced'
        : 'NO LIVE VEHICLE SNAPSHOT · Dealer searches below remain available';
      coverage();
      for(const id of ['max-price','max-mileage','max-distance','sort','awd','local']) $(id).addEventListener('input',render);
      $('expand-mileage').addEventListener('click',()=>{
        $('max-mileage').value='100000';
        render();
      });
      render();
    }catch(error){
      $('meta').textContent='Vehicle catalog unavailable · '+error.message;
      $('empty-state').hidden=false;
      $('empty-description').textContent='There is no current vehicle file. We are not displaying unverified car listings.';
      $('grid').replaceChildren();
    }
  }
  load();
})();
