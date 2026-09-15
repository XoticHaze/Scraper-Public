let catalog = null;
const byId = (id) => document.getElementById(id);
const money = (n) => n == null ? '—' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(n);
const number = (n) => n == null ? '—' : new Intl.NumberFormat('en-US').format(n);
const text = (value) => String(value || '').replaceAll('_', ' ');

function metric(label, value) {
  return `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`;
}

function localityPass(v, maxDistance, localOnly) {
  const bucket = String(v.locality || '').toLowerCase();
  const distance = v.distance_miles == null ? null : Number(v.distance_miles);
  const trustedLocality = bucket === 'local' || bucket === 'nearby';
  if (localOnly && !trustedLocality && !(distance != null && distance <= 50)) return false;
  if (distance != null) return distance <= maxDistance;
  return trustedLocality || maxDistance >= 200;
}

function renderSourceCoverage() {
  const counts = catalog.source_counts || {};
  const errors = catalog.source_errors || {};
  const healthy = Object.entries(counts).map(([name,count]) => `${name}: ${count}`).join(' · ');
  const degraded = Object.keys(errors);
  byId('source-status').textContent = `${healthy || 'No source counts'}${degraded.length ? ` · degraded: ${degraded.join(', ')}` : ''}`;

  const sourceLinks = byId('source-links');
  sourceLinks.innerHTML = '';
  for (const source of (catalog.source_registry || [])) {
    if (!source.inventory_url) continue;
    const a = document.createElement('a');
    a.href = source.inventory_url;
    a.target = '_blank';
    a.rel = 'noreferrer';
    a.textContent = `${source.name || source.id}${source.location ? ` · ${source.location}` : ''}`;
    sourceLinks.appendChild(a);
  }

  const discoveryLinks = byId('discovery-links');
  discoveryLinks.innerHTML = '';
  for (const route of (catalog.discovery_routes || [])) {
    const a = document.createElement('a');
    a.href = route.url;
    a.target = '_blank';
    a.rel = 'noreferrer';
    a.textContent = route.label || route.id;
    if (route.warning) a.title = route.warning;
    discoveryLinks.appendChild(a);
  }
}

function render() {
  if (!catalog) return;
  const maxPrice = Number(byId('max-price').value || Infinity);
  const maxMileage = Number(byId('max-mileage').value || Infinity);
  const maxDistance = Number(byId('max-distance').value || Infinity);
  const awdOnly = byId('awd').checked;
  const localOnly = byId('local').checked;
  const rows = (catalog.vehicles || []).filter((v) =>
    Number(v.price) <= maxPrice && Number(v.mileage) <= maxMileage && localityPass(v, maxDistance, localOnly) &&
    (!awdOnly || /all-wheel|awd/i.test(v.drivetrain || ''))
  );
  byId('count').textContent = number(rows.length);
  const grid = byId('grid');
  grid.innerHTML = '';
  for (const v of rows) {
    const card = document.createElement('article');
    card.className = 'card';
    const reasons = (v.reasons || []).map((r) => `<span class="tag">${text(r)}</span>`).join('');
    const risks = (v.risks || []).map((r) => `<span class="tag risk">${text(r)}</span>`).join('');
    const image = v.image_url ? `<img src="${v.image_url}" alt="" loading="lazy" />` : '';
    const priceMove = v.price_delta == null ? 'new' : money(v.price_delta);
    const listing = v.source_url ? `<a href="${v.source_url}" target="_blank" rel="noreferrer">Open dealer listing</a>` : '';
    const addon = v.dealer_addon_warning ? `<p class="warning">${v.dealer_addon_warning}</p>` : '';
    card.innerHTML = `${image}<div class="body"><div class="badges"><b>#${v.rank}</b><span>score ${v.deal_score}</span><span>${v.locality}${v.distance_miles == null ? '' : ` · ${v.distance_miles} mi`}</span></div><h2>${v.title || `${v.year} ${v.make} ${v.model}`}</h2><p>${[v.dealer,v.location].filter(Boolean).join(' · ') || 'Dealer/location pending verification'}</p><div class="metrics">${metric('Price',money(v.price))}${metric('Est. OTD',money(v.estimated_otd))}${metric('Mileage',number(v.mileage))}${metric('Drivetrain',v.drivetrain || '—')}${metric('vs comps',v.market_delta_pct == null ? '—' : `${v.market_delta_pct}%`)}${metric('Price move',priceMove)}</div><div class="tags">${reasons}${risks}</div>${addon}${listing}</div>`;
    grid.appendChild(card);
  }
}

async function load() {
  try {
    const response = await fetch(`vehicle_catalog.json?t=${Date.now()}`, {cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    catalog = await response.json();
    const market = catalog.market || {};
    byId('meta').textContent = `${catalog.eligible_count || 0} eligible · ${market.label || 'San Antonio, TX'} · preferred within ${market.preferred_radius_miles || 50} mi · updated ${new Date(catalog.generated_utc).toLocaleString()}`;
    ['max-price','max-mileage','max-distance','awd','local'].forEach((id) => byId(id).addEventListener('input', render));
    renderSourceCoverage();
    render();
  } catch (error) {
    byId('meta').textContent = 'No published vehicle catalog yet. The scheduled vehicle refresh has not produced a last-good catalog.';
    byId('source-status').textContent = String(error);
    byId('grid').textContent = String(error);
  }
}

load();
