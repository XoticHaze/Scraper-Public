const $ = (selector) => document.querySelector(selector);
const grid = $('#grid');
const template = $('#card-template');
const dialog = $('#detail-dialog');
const detailContent = $('#detail-content');

const state = {
  catalog: null,
  sort: 'ending',
  query: '',
  category: '',
  condition: '',
  closesWithin: null,
  minRetail: null,
  maxTotal: null,
  noBidders: false,
  watchOnly: false,
  visible: 160,
  watchlist: window.MacbidBrowserState?.watchlistSet?.() ?? new Set(JSON.parse(localStorage.getItem('macbid-hunt-watchlist') || '[]')),
};

function money(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }) : '—';
}

function number(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function closeText(epoch) {
  const seconds = Number(epoch) - Date.now() / 1000;
  if (!Number.isFinite(seconds)) return 'Unknown';
  if (seconds <= 0) return 'Ended';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}

function localClose(epoch) {
  const n = Number(epoch);
  return Number.isFinite(n) ? new Date(n * 1000).toLocaleString() : 'Unknown';
}

function pct(value) {
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(1)}%` : '—';
}

function lotAllIn(lot) {
  return number(lot.estimated_post_tax_total ?? lot.estimated_all_in_total ?? lot.estimated_pre_tax_total);
}

function itemMetadata(identity) {
  return window.MacbidBrowserState?.getItemMetadata?.(identity) || {};
}

function effectiveCeilings(product, lot) {
  const meta = itemMetadata(product.identity);
  return {
    maxBid: number(meta.max_bid) ?? number(lot.verified_max_bid ?? lot.max_bid),
    maxAllIn: number(meta.max_all_in) ?? number(lot.max_all_in),
    personalMaxBid: number(meta.max_bid),
    personalMaxAllIn: number(meta.max_all_in),
  };
}

function headroomAmount(current, ceiling) {
  const now = number(current);
  const max = number(ceiling);
  return now !== null && max !== null ? max - now : null;
}

function saveWatchlist() {
  if (window.MacbidBrowserState?.replaceWatchlist) {
    state.watchlist = window.MacbidBrowserState.replaceWatchlist([...state.watchlist]);
    return;
  }
  localStorage.setItem('macbid-hunt-watchlist', JSON.stringify([...state.watchlist]));
}

function toggleWatch(identity) {
  if (state.watchlist.has(identity)) state.watchlist.delete(identity);
  else state.watchlist.add(identity);
  saveWatchlist();
  render();
}

function activeLots(product) {
  const now = Date.now() / 1000;
  return product.lots.filter((lot) => {
    const close = number(lot.expected_closing_utc);
    if (close !== null && close <= now) return false;
    if (state.condition && lot.condition !== state.condition) return false;
    if (state.noBidders && Number(lot.unique_bidders || 0) !== 0) return false;
    if (state.minRetail !== null && Number(lot.retail_price ?? 0) < state.minRetail) return false;
    if (state.maxTotal !== null && Number(lotAllIn(lot) ?? Infinity) > state.maxTotal) return false;
    if (state.closesWithin !== null && (close === null || close > now + state.closesWithin * 3600)) return false;
    return true;
  });
}

function marketValueRank(lot) {
  if (lot.market_price_status === 'verified_external' && number(lot.verified_discount_pct) !== null) {
    return 1000 + Number(lot.verified_discount_pct) - Number(lot.unique_bidders || 0) * 2;
  }
  // Unverified listings are discovery candidates, not MSRP-derived deals.
  return -Number(lot.unique_bidders || 0) * 2;
}

function lotComparator(mode) {
  if (mode === 'value') {
    return (a, b) => marketValueRank(b) - marketValueRank(a) || Number(a.expected_closing_utc || Infinity) - Number(b.expected_closing_utc || Infinity);
  }
  if (mode === 'competition') {
    return (a, b) => Number(a.unique_bidders || 0) - Number(b.unique_bidders || 0) || Number(a.total_bids || 0) - Number(b.total_bids || 0) || Number(b.deal_score || -9999) - Number(a.deal_score || -9999);
  }
  if (mode === 'cost') {
    return (a, b) => Number(lotAllIn(a) ?? Infinity) - Number(lotAllIn(b) ?? Infinity) || Number(b.deal_score || -9999) - Number(a.deal_score || -9999);
  }
  return (a, b) => Number(a.expected_closing_utc || Infinity) - Number(b.expected_closing_utc || Infinity) || Number(b.deal_score || -9999) - Number(a.deal_score || -9999);
}

function chooseLot(lots) {
  return [...lots].sort(lotComparator(state.sort))[0];
}

function productMatchesSearch(product) {
  if (!state.query) return true;
  const haystack = [product.name, product.brand, product.category, product.upc, product.model]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return state.query.split(/\s+/).every((token) => haystack.includes(token));
}

function rows() {
  const mapped = [];
  for (const product of state.catalog.products) {
    if (state.category && product.category !== state.category) continue;
    if (state.watchOnly && !state.watchlist.has(product.identity)) continue;
    if (!productMatchesSearch(product)) continue;
    const lots = activeLots(product);
    if (!lots.length) continue;
    mapped.push({ product, lots, lot: chooseLot(lots) });
  }
  const cmp = lotComparator(state.sort);
  mapped.sort((a, b) => cmp(a.lot, b.lot));
  return mapped;
}

function chip(text, cls = '') {
  const el = document.createElement('span');
  el.className = `chip ${cls}`.trim();
  el.textContent = text;
  return el;
}

function metric(label, value, cls = '') {
  const el = document.createElement('div');
  el.className = 'metric';
  const l = document.createElement('span');
  l.textContent = label;
  const v = document.createElement('strong');
  v.className = cls;
  v.textContent = value;
  el.append(l, v);
  return el;
}

function renderCard(row) {
  const { product, lot, lots } = row;
  const node = template.content.cloneNode(true);
  const card = node.querySelector('.card');
  const open = node.querySelector('.card-open');
  const img = node.querySelector('img');
  const chips = node.querySelector('.chips');
  const title = node.querySelector('h2');
  const brand = node.querySelector('.brand');
  const metrics = node.querySelector('.metrics');
  const foot = node.querySelector('.card-foot');
  const star = node.querySelector('.watch-star');

  const image = lot.image_url || product.image_url;
  if (image) img.src = image;
  img.alt = product.name;
  img.onerror = () => { img.style.opacity = '.18'; img.removeAttribute('src'); };

  chips.append(chip(lot.condition === 'LIKE NEW' ? 'Like New' : 'Open Box', lot.condition === 'LIKE NEW' ? 'good' : 'warn'));
  if (lot.market_price_status === 'verified_external') chips.append(chip('Market verified', 'good'));
  const compatibility = product.compatibility || {};
  const compatibilityLabels = {
    verified: ['HAOS verified', 'good'],
    verified_with_requirements: ['HAOS + prerequisites', 'good'],
    variant_required: ['HAOS variant check', 'warn'],
    candidate: ['HAOS candidate', 'warn'],
    ruled_out: ['HAOS ruled out', 'warn'],
  };
  const compatibilityChip = compatibilityLabels[compatibility.status];
  if (compatibilityChip) chips.append(chip(compatibilityChip[0], compatibilityChip[1]));
  if (Number.isFinite(Number(product.rated_wattage))) {
    const watts = Number(product.rated_wattage);
    chips.append(chip(watts >= 1000 ? `${(watts / 1000).toFixed(watts % 1000 ? 1 : 0)} kW` : `${watts.toFixed(0)}W`, watts >= 500 ? 'good' : ''));
  }
  if (lot.market_value_freshness === 'aging') chips.append(chip('Price aging', 'warn'));
  if (lot.market_price_status === 'stale_external') chips.append(chip('Price stale', 'warn'));
  const cardCeilings = effectiveCeilings(product, lot);
  if (cardCeilings.personalMaxBid !== null || cardCeilings.personalMaxAllIn !== null) chips.append(chip('Your max', 'good'));
  if (lots.length > 1) chips.append(chip(`${lots.length} lots`));
  title.textContent = product.name;
  brand.textContent = [product.brand, product.category].filter(Boolean).join(' · ');

  const marketMedian = product.verified_new_price ?? lot.verified_new_price;
  metrics.append(
    metric('Current bid', money(lot.current_bid)),
    metric('Est. all-in', money(lotAllIn(lot)), 'good'),
    metric(marketMedian != null ? 'Ext. median' : 'Stated retail', money(marketMedian ?? lot.retail_price ?? product.retail_price)),
    metric('Closes', closeText(lot.expected_closing_utc))
  );
  metrics.lastElementChild.querySelector('strong').dataset.close = lot.expected_closing_utc || '';

  const left = document.createElement('span');
  left.textContent = `${Number(lot.unique_bidders || 0)} bidders · ${Number(lot.total_bids || 0)} bids`;
  const right = document.createElement('span');
  const allInHeadroom = headroomAmount(lotAllIn(lot), cardCeilings.maxAllIn);
  right.textContent = allInHeadroom !== null
    ? (allInHeadroom >= 0 ? `${money(allInHeadroom)} headroom` : `${money(Math.abs(allInHeadroom))} over max`)
    : lot.market_price_status === 'verified_external'
      ? `${pct(lot.verified_discount_pct)} vs market`
      : 'Independent value unverified';
  foot.append(left, right);

  if (state.watchlist.has(product.identity)) {
    star.classList.add('active');
    star.textContent = '★';
  }
  star.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleWatch(product.identity);
  });
  open.addEventListener('click', () => openDetails(row));
  card.dataset.identity = product.identity;
  return node;
}

function protectedOfferMarkup(product) {
  const comparison = product.protected_offer_comparison;
  if (!comparison?.offers?.length) return '<div class="verify-box"><strong>Protected purchase alternatives</strong><p class="muted">No independently verified delivered offer for this exact product. External market references are not purchase-ready quotes.</p></div>';
  const rows = comparison.offers.filter(o => /^https:\/\//i.test(o.url || '')).map(o =>
    `<div class="cost-row"><a href="${escapeHtml(o.url)}" target="_blank" rel="noreferrer">${escapeHtml(o.source_label || 'External offer')}</a><strong>${money(o.price)} · ${escapeHtml(o.availability || 'unknown')}</strong></div><p class="muted">${escapeHtml(o.condition || 'unknown condition')} · Shipping ${money(o.shipping)} · Fees ${money(o.mandatory_fees)} · ${o.eligible ? 'Verified delivered' : 'Est. delivered'} ${money(o.eligible ? o.verified_delivered_total : o.estimated_delivered_total)} · Returns ${o.return_days ?? 'unknown'} days · Warranty ${o.warranty_days ?? 'unknown'} days · ${o.eligible ? 'Protected comparator' : 'Not verified for bidding'} · ${escapeHtml(o.evidence_note || '')}</p>`).join('');
  return `<div class="verify-box"><strong>Protected purchase alternatives</strong>${rows}<div class="cost-row"><span>More than 50% savings auction ceiling</span><strong>${money(comparison.max_auction_all_in)}</strong></div><div class="cost-row"><span>Max hammer before additional risk adjustments</span><strong>${money(comparison.max_auction_hammer)}</strong></div><p class="muted">No ceiling from cached, unavailable or incomplete offers. Only eligible offers have a verified checkout total; auction fees and tax are estimated. Recheck item and condition.</p></div>`;
}

function localProtectedQuoteMarkup() {
  return `<div class="plan-box" id="local-protected-quote">
    <strong>Compare a returnable checkout quote · browser-local</strong>
    <p class="muted">Use a current, exact-item alternative you have checked. Include shipping, tax and all mandatory fees in its delivered price. This scenario is not independently verified or published, and does not change your saved plan.</p>
    <div class="plan-grid">
      <label>Alternative delivered total ($)<input id="quote-total" type="number" min="0.01" step="0.01" placeholder="Full checkout total"></label>
      <label>Auction protection / extra costs ($)<input id="quote-extra" type="number" min="0" step="0.01" placeholder="Enter 0 if none"></label>
      <label>Return window (days)<input id="quote-returns" type="number" min="1" max="365" step="1" placeholder="Item-specific"></label>
    </div>
    <label class="plan-note"><input id="quote-exact" type="checkbox"> I confirmed exact model, condition, reputable seller, stock and return eligibility.</label>
    <p class="muted">Auction protection is optional and item-specific. Enter the actual quoted amount including tax, plus transport/other incremental costs. Do not assume protection is available.</p>
    <div id="quote-result" aria-live="polite" class="muted">Complete all fields to calculate a comparison.</div>
  </div>`;
}

function wireLocalProtectedQuote(lot, premiumRate, fee, taxRate) {
  const box = detailContent.querySelector('#local-protected-quote');
  if (!box) return;
  const get = id => box.querySelector('#' + id);
  const update = () => {
    const delivered = number(get('quote-total').value);
    const extra = number(get('quote-extra').value);
    const returns = number(get('quote-returns').value);
    const out = get('quote-result');
    if (!(delivered > 0) || extra === null || extra < 0 || !Number.isInteger(returns) || returns < 1 || returns > 365 || !get('quote-exact').checked) {
      out.textContent = 'Complete all fields and confirm return eligibility and exact identity. No bid ceiling yet.';
      return;
    }
    const max = Math.max(0, Math.ceil(delivered * 50 - 1e-8) - 1) / 100;
    const auctionOnly = Math.max(0, max - extra);
    const hammer = Math.floor((auctionOnly / (1 + taxRate) - fee) / (1 + premiumRate) * 100) / 100;
    const current = lotAllIn(lot);
    const existing = lot.market_value_authoritative ? number(lot.verified_max_bid) : null;
    const safe = hammer >= 0 ? (existing !== null ? Math.min(existing, hammer) : hammer) : null;
    out.textContent = 'Strictly below half of delivered alternative: ' + money(max) +
      ' · Current auction including extras: ' + (current === null ? 'unknown' : money(current + extra)) +
      ' · Scenario maximum hammer: ' + (safe === null ? 'No feasible bid' : money(safe)) +
      (existing !== null ? ' (also capped by independent valuation)' : ' (local quote only; independent value unverified)') +
      '. Check actual fees, condition and final checkout before purchase.';
  };
  box.querySelectorAll('input').forEach(input => input.addEventListener('input', update));
  update();
}

function verifiedMarkup(product, lot) {
  const status = product.market_price_status || lot.market_price_status || 'unverified';
  const market = product.market_value || {};
  const currentNew = market.current_new || {};
  const history = market.price_history || {};
  const verifiedNew = product.verified_new_price ?? lot.verified_new_price;
  const average = product.current_new_average ?? lot.current_new_average ?? currentNew.average;
  const low = product.current_new_low ?? lot.current_new_low ?? currentNew.low;
  const high = product.current_new_high ?? lot.current_new_high ?? currentNew.high;
  const samples = product.current_new_samples ?? lot.current_new_samples ?? currentNew.samples;
  const openBoxValue = product.realistic_open_box_value ?? lot.realistic_open_box_value;
  const maxAllIn = lot.max_all_in;
  const maxBid = lot.verified_max_bid ?? lot.max_bid;
  const confidence = product.market_value_confidence || lot.market_value_confidence || market.price_confidence;
  const observed = product.market_value_observed_at || lot.market_value_observed_at || market.observed_at;
  const sourceLinks = (market.sources || [])
    .filter((source) => source?.url && /^https:\/\//i.test(source.url))
    .slice(0, 8)
    .map((source) => `<a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.label || 'Source')} · ${money(source.price)} · ${escapeHtml(source.condition || 'condition unknown')} · ${escapeHtml(source.observed_at || 'date unknown')} ↗</a>`)
    .join(' · ');
  if (!['verified_external', 'stale_external'].includes(status) || (verifiedNew == null && openBoxValue == null)) {
    return `<div class="verify-box"><strong>External market verification</strong><p class="muted">Not verified yet. MAC.BID retail is discovery-only until exact identity is matched to external current-market observations.</p></div>`;
  }
  const freshness = product.market_value_freshness || lot.market_value_freshness || 'unknown';
  const ageDays = product.market_value_age_days ?? lot.market_value_age_days;
  const authoritative = product.market_value_authoritative ?? lot.market_value_authoritative;
  return `<div class="verify-box">
    <strong>External market valuation</strong>
    <div class="cost-row"><span>Price freshness</span><strong class="${freshness === 'fresh' ? 'good' : ''}">${escapeHtml(freshness)}${ageDays != null ? ` · ${ageDays}d old` : ''}</strong></div>
    <div class="cost-row"><span>Current-new median</span><strong>${money(verifiedNew)}</strong></div>
    <div class="cost-row"><span>Current-new average</span><strong>${money(average)}</strong></div>
    <div class="cost-row"><span>Observed range</span><strong>${money(low)} – ${money(high)}</strong></div>
    <div class="cost-row"><span>Samples / confidence</span><strong>${Number(samples || 0)} · ${escapeHtml(confidence || 'unknown')}</strong></div>
    ${history.average != null ? `<div class="cost-row"><span>Tracked historical avg.</span><strong>${money(history.average)}</strong></div>` : ''}
    <div class="cost-row"><span>Realistic open-box value</span><strong>${money(openBoxValue)}</strong></div>
    <div class="cost-row"><span>Current discount vs market</span><strong class="good">${pct(lot.verified_discount_pct)}</strong></div>
    <div class="cost-row total"><span>Max all-in allocation</span><strong>${authoritative ? money(maxAllIn) : 'Refresh required'}</strong></div>
    <div class="cost-row total"><span>Max hammer bid</span><strong>${authoritative ? money(maxBid) : 'Refresh required'}</strong></div>
    <p class="muted">${authoritative ? 'External pricing is within the active freshness window.' : 'External pricing is stale or undated, so it is shown for context but cannot drive an automatic bid ceiling.'} Observed ${escapeHtml(observed || 'unknown date')}. MAC.BID stated retail is reference-only for this item.</p>
    ${sourceLinks ? `<div class="research-sources">${sourceLinks}</div>` : ''}
  </div>`;
}

function observedBidMarkup(lot) {
  const observed=lot.observed_bid_history;
  if (!observed || !observed.retained_points) return '';
  const points=(observed.recent_points || []).map(([epoch,amount]) => `<div class="cost-row"><span>${escapeHtml(new Date(epoch*1000).toLocaleString())}</span><strong>${money(amount)}</strong></div>`).join('');
  return `<div class="verify-box"><strong>Observed bid trajectory</strong><div class="cost-row"><span>First → latest captured bid</span><strong>${money(observed.first_observed_hammer)} → ${money(observed.latest_observed_hammer)}</strong></div><p class="muted">${Number(observed.retained_points)} retained actual observations${observed.display_is_sampled ? ' · showing a bounded sample' : ''}. These are snapshots, not a complete bid history or final sale price.</p>${points}</div>`;
}

function historicalAcquisitionMarkup(product, lot) {
  const coverage = state.catalog?.historical_acquisition || {};
  const group = (product.historical_acquisition?.cohorts || []).find(c => c.location === lot.auction_location && c.condition === lot.condition);
  const live = group?.prospective || {};
  const sample = group?.selected_historical_sample || {};
  const legacy = group?.recovered_legacy_scope || {};
  const rows = [
    ['Comparable verified closes', Number(live.verified_sold || 0)],
    ['Comparable confirmed unsold', Number(live.verified_unsold || 0)],
    ['Comparable unresolved', Number(live.unresolved || 0)],
    ['Observed all-in median (current fee estimate)', live.verified_sold ? money(live.estimated_all_in_p50) : 'Insufficient evidence'],
    ['Selected older sample / sold', Number(sample.verified_sold || 0)],
    ['Recovered legacy / verified sold', Number(legacy.verified_sold || 0)],
    ['Recovered legacy / unresolved', Number(legacy.unresolved || 0)],
    ['Recovered legacy all-in median', legacy.verified_sold ? money(legacy.estimated_all_in_p50) : 'Insufficient evidence']
  ].map(([label,value]) => `<div class="cost-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`).join('');
  const links = (group?.recent_verified_closes || []).filter(r => /^https:\/\/www\.mac\.bid\/auction\/[A-Z0-9-]+\/lot\/[A-Z0-9-]+$/.test(r.lot_url || "")).map(r => `<div class="cost-row"><a href="${escapeHtml(r.lot_url)}" target="_blank" rel="noreferrer">${escapeHtml(r.auction_number)} / ${escapeHtml(r.lot_number)}</a><strong>${r.status === "closed_sold_verified" ? money(r.final_hammer) : "Not sold"} · ${escapeHtml(r.scope.replaceAll("_"," "))}</strong></div>`).join("");
  return `<div class="verify-box"><strong>Historical acquisition evidence</strong>${rows}${links ? `<p class="muted">Recent verified hammer prices (source links)</p>${links}` : ""}<p class="muted">Same exact identity, location and condition only. Older selected and recovered scopes are descriptive, not prospective training evidence. ${Number(coverage.complete_days || 0)} hourly-covered UTC days in retained scope; at least 30 consecutive hourly-covered days and 20 comparable prior verified sales required for chronological evaluation. No sale probability or expected wait inferred.</p></div>`;
}

function compatibilityMarkup(product) {
  const compatibility = product.compatibility || {};
  const status = compatibility.status || 'unknown';
  const labels = {
    verified: 'HAOS verified',
    verified_with_requirements: 'HAOS verified with prerequisites',
    variant_required: 'HAOS variant must be confirmed',
    candidate: 'HAOS candidate',
    unknown: 'HAOS compatibility unknown',
    ruled_out: 'HAOS ruled out',
  };
  const requirements = (compatibility.requirements || [])
    .map((value) => `<li>${escapeHtml(value)}</li>`)
    .join('');
  const paths = (compatibility.detected_paths || [])
    .map((path) => [path.integration, path.status].filter(Boolean).join(' · '))
    .filter(Boolean)
    .slice(0, 6)
    .map((value) => `<li>${escapeHtml(value)}</li>`)
    .join('');
  const sources = [
    ...(compatibility.sources || []),
    ...(compatibility.source ? [compatibility.source] : []),
  ]
    .filter((value, index, all) => value && all.indexOf(value) === index && /^https:\/\//i.test(value))
    .slice(0, 6)
    .map((value) => `<a href="${escapeHtml(value)}" target="_blank" rel="noreferrer">Compatibility source ↗</a>`)
    .join(' · ');
  return `<div class="verify-box">
    <strong>Compatibility · ${escapeHtml(labels[status] || status)}</strong>
    <div class="cost-row"><span>Integration/path</span><strong>${escapeHtml(compatibility.integration || 'Not established')}</strong></div>
    <div class="cost-row"><span>Evidence basis</span><strong>${escapeHtml(compatibility.basis || 'none')}</strong></div>
    <div class="cost-row"><span>Local control</span><strong>${escapeHtml(compatibility.local_control === true ? 'Yes' : compatibility.local_control === false ? 'No' : compatibility.local_control || 'Unknown')}</strong></div>
    ${compatibility.model ? `<div class="cost-row"><span>Exact model</span><strong>${escapeHtml(compatibility.model)}</strong></div>` : ''}
    ${compatibility.note ? `<p class="muted">${escapeHtml(compatibility.note)}</p>` : ''}
    ${requirements ? `<div class="compat-list"><strong>Requirements</strong><ul>${requirements}</ul></div>` : ''}
    ${paths ? `<div class="compat-list"><strong>Detected paths</strong><ul>${paths}</ul></div>` : ''}
    ${sources ? `<div class="research-sources">${sources}</div>` : ''}
  </div>`;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[char]));
}

function safeMacUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && (url.hostname === 'www.mac.bid' || url.hostname === 'mac.bid') ? url.href : '#';
  } catch { return '#'; }
}

function macProductUrl(product, lot = {}) {
  const key = product?.upc || lot?.upc || product?.asin || lot?.asin;
  if (key) return safeMacUrl(`https://www.mac.bid/products/${encodeURIComponent(String(key))}`);
  return safeMacUrl(lot?.macbid_url);
}

function lotRef(lot) {
  return [lot?.auction_number, lot?.lot_number ? `lot ${lot.lot_number}` : ''].filter(Boolean).join(' · ');
}

function macLookupKey(product, lot = {}) {
  return String(product?.upc || lot?.upc || product?.asin || lot?.asin || product?.name || '').trim();
}

async function copyText(value, button) {
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const input = document.createElement('textarea');
    input.value = value;
    input.setAttribute('readonly', '');
    input.style.position = 'fixed';
    input.style.opacity = '0';
    document.body.append(input);
    input.select();
    document.execCommand('copy');
    input.remove();
  }
  if (button) {
    const original = button.textContent;
    button.textContent = 'Copied ✓';
    setTimeout(() => { button.textContent = original; }, 1400);
  }
}

function openDetails(row) {
  const { product, lot } = row;
  const bid = Number(lot.current_bid || 0);
  const premiumRate = Number(state.catalog.buyer_premium_rate || 0.15);
  const premium = bid * premiumRate;
  const fee = Number(state.catalog.lot_fee || 3);
  const taxRate = Number(state.catalog.sales_tax_rate || lot.sales_tax_rate || 0);
  const subtotal = number(lot.estimated_pre_tax_total) ?? (bid + premium + fee);
  const estimatedTax = number(lot.estimated_sales_tax) ?? subtotal * taxRate;
  const allIn = lotAllIn(lot) ?? subtotal + estimatedTax;
  const meta = itemMetadata(product.identity);
  const ceilings = effectiveCeilings(product, lot);
  const bidHeadroom = headroomAmount(bid, ceilings.maxBid);
  const allInHeadroom = headroomAmount(allIn, ceilings.maxAllIn);
  const image = lot.image_url || product.image_url || '';
  const altRows = [...product.lots]
    .filter((entry) => Number(entry.expected_closing_utc || 0) > Date.now() / 1000)
    .sort((a, b) => Number(a.expected_closing_utc || Infinity) - Number(b.expected_closing_utc || Infinity))
    .slice(0, 20)
    .map((entry) => `<div class="alt"><span>${escapeHtml(entry.condition || '')} · ${money(entry.current_bid)} · ${money(lotAllIn(entry))} all-in · ${closeText(entry.expected_closing_utc)}</span><span>${Number(entry.unique_bidders || 0)} bidders · ${escapeHtml(lotRef(entry))}</span><a href="${macProductUrl(product, entry)}" target="_blank" rel="noreferrer">Open product ↗</a></div>`)
    .join('');

  detailContent.innerHTML = `<div class="detail">
    <div class="detail-media">${image ? `<img src="${escapeHtml(image)}" alt="${escapeHtml(product.name)}">` : ''}</div>
    <div class="detail-body">
      <div class="chips"><span class="chip ${lot.condition === 'LIKE NEW' ? 'good' : 'warn'}">${escapeHtml(lot.condition)}</span><span class="chip">${escapeHtml(product.category || 'Uncategorized')}</span>${product.compatibility?.status ? `<span class="chip ${['verified','verified_with_requirements'].includes(product.compatibility.status) ? 'good' : 'warn'}">${escapeHtml((product.compatibility.status === 'verified' ? 'HAOS verified' : product.compatibility.status === 'verified_with_requirements' ? 'HAOS + prerequisites' : product.compatibility.status === 'variant_required' ? 'HAOS variant check' : product.compatibility.status === 'candidate' ? 'HAOS candidate' : product.compatibility.status === 'ruled_out' ? 'HAOS ruled out' : 'HAOS unknown'))}</span>` : ''}${product.lot_count > 1 ? `<span class="chip">${product.lot_count} lots</span>` : ''}</div>
      <h2>${escapeHtml(product.name)}</h2>
      <p class="sub">${escapeHtml([product.brand, product.model, product.upc ? `UPC ${product.upc}` : null].filter(Boolean).join(' · '))}</p>
      <div class="cost-box">
        <div class="cost-row"><span>Current bid</span><strong>${money(bid)}</strong></div>
        <div class="cost-row"><span>Buyer premium (${(premiumRate * 100).toFixed(0)}%)</span><strong>${money(premium)}</strong></div>
        <div class="cost-row"><span>Lot fee</span><strong>${money(fee)}</strong></div>
        <div class="cost-row"><span>Estimated pre-tax subtotal</span><strong>${money(subtotal)}</strong></div>
        <div class="cost-row"><span>Estimated sales tax (${(taxRate * 100).toFixed(2)}%)</span><strong>${money(estimatedTax)}</strong></div>
        <div class="cost-row total"><span>Estimated all-in total</span><strong class="good">${money(allIn)}</strong></div>
        <div class="cost-row"><span>MAC.BID stated retail</span><strong>${money(lot.retail_price || product.retail_price)}</strong></div>
        <div class="cost-row"><span>Independent max bid</span><strong>${lot.market_value_authoritative ? money(lot.verified_max_bid) : "Not verified"}</strong></div>
      </div>
      <p class="muted">Sales tax is an estimate using the active catalog tax profile and current assumed taxable basis. MAC.BID stated retail is reference-only and does not establish savings or a purchase ceiling.</p>
      ${verifiedMarkup(product, lot)}
      ${protectedOfferMarkup(product)}
      ${localProtectedQuoteMarkup()}
      ${observedBidMarkup(lot)}
      ${historicalAcquisitionMarkup(product, lot)}
      ${compatibilityMarkup(product)}
      <div class="plan-box">
        <strong>Your plan · browser-local</strong>
        <div class="cost-row"><span>Effective max bid</span><strong>${money(ceilings.maxBid)}</strong></div>
        <div class="cost-row"><span>Bid headroom</span><strong class="${bidHeadroom != null && bidHeadroom >= 0 ? 'good' : ''}">${bidHeadroom == null ? '—' : bidHeadroom >= 0 ? money(bidHeadroom) : `${money(Math.abs(bidHeadroom))} over`}</strong></div>
        <div class="cost-row"><span>Effective max all-in</span><strong>${money(ceilings.maxAllIn)}</strong></div>
        <div class="cost-row"><span>All-in headroom</span><strong class="${allInHeadroom != null && allInHeadroom >= 0 ? 'good' : ''}">${allInHeadroom == null ? '—' : allInHeadroom >= 0 ? money(allInHeadroom) : `${money(Math.abs(allInHeadroom))} over`}</strong></div>
        <div class="plan-grid">
          <label>Your max bid<input id="plan-max-bid" type="number" min="0" step="1" value="${escapeHtml(meta.max_bid ?? '')}" placeholder="${escapeHtml(lot.verified_max_bid ?? '')}"></label>
          <label>Your max all-in<input id="plan-max-all-in" type="number" min="0" step="1" value="${escapeHtml(meta.max_all_in ?? '')}" placeholder="${escapeHtml(lot.max_all_in ?? '')}"></label>
          <label>Status<select id="plan-status">
            <option value="" ${!meta.status ? 'selected' : ''}>Unspecified</option>
            <option value="watch" ${meta.status === 'watch' ? 'selected' : ''}>Watch</option>
            <option value="buy-zone" ${meta.status === 'buy-zone' ? 'selected' : ''}>Buy zone</option>
            <option value="pass" ${meta.status === 'pass' ? 'selected' : ''}>Pass</option>
            <option value="won" ${meta.status === 'won' ? 'selected' : ''}>Won</option>
          </select></label>
          <label>Tags<input id="plan-tags" type="text" value="${escapeHtml((meta.tags || []).join(', '))}" placeholder="home, haos, tool"></label>
        </div>
        <label class="plan-note">Notes<textarea id="plan-note" rows="3" placeholder="Condition, fit, missing parts, why we want it…">${escapeHtml(meta.note || '')}</textarea></label>
        <div class="detail-actions"><button id="save-plan" type="button">Save plan</button></div>
      </div>
      <div class="lot-box">
        <strong>Lot state</strong>
        <div class="cost-row"><span>Closes</span><strong data-close="${escapeHtml(lot.expected_closing_utc || '')}">${closeText(lot.expected_closing_utc)}</strong></div>
        <div class="cost-row"><span>Local close time</span><strong>${escapeHtml(localClose(lot.expected_closing_utc))}</strong></div>
        <div class="cost-row"><span>Competition</span><strong>${Number(lot.unique_bidders || 0)} bidders · ${Number(lot.total_bids || 0)} bids</strong></div>
        <div class="cost-row"><span>Deal discovery score</span><strong>${Number(lot.deal_score || 0).toFixed(1)}</strong></div>
        <div class="cost-row"><span>Target lot</span><strong>${escapeHtml(lotRef(lot) || 'Unknown')}</strong></div>
      </div>
      ${product.lot_count > 1 ? `<div class="lot-box"><strong>Other active lots</strong><div class="alt-list">${altRows}</div></div>` : ''}
      <p class="muted">iPhone note: MAC.BID currently opens from universal links without reliably navigating to the linked item. If that happens, copy the item ID into MAC.BID search, or copy the web link and paste it into Safari's address bar.</p>
      <div class="detail-actions">
        <a class="primary-link" href="${macProductUrl(product, lot)}" target="_blank" rel="noreferrer">MAC.BID page ↗</a>
        <button id="copy-web-link" type="button">Copy web link</button>
        <button id="copy-mac-id" type="button">Copy item ID</button>
        <button id="copy-lot-ref" type="button">Copy lot ref</button>
        <button id="detail-watch" type="button">${state.watchlist.has(product.identity) ? '★ Watching' : '☆ Add to watchlist'}</button>
      </div>
    </div>
  </div>`;
  wireLocalProtectedQuote(lot, premiumRate, fee, taxRate);
  detailContent.querySelector('#copy-web-link')?.addEventListener('click', (event) => {
    copyText(macProductUrl(product, lot), event.currentTarget);
  });
  detailContent.querySelector('#copy-mac-id')?.addEventListener('click', (event) => {
    copyText(macLookupKey(product, lot), event.currentTarget);
  });
  detailContent.querySelector('#copy-lot-ref')?.addEventListener('click', (event) => {
    copyText(lotRef(lot), event.currentTarget);
  });
  detailContent.querySelector('#save-plan')?.addEventListener('click', (event) => {
    if (!window.MacbidBrowserState?.updateItemMetadata) return;
    const parseOptional = (selector) => {
      const raw = detailContent.querySelector(selector)?.value?.trim() || '';
      return raw === '' ? null : Number(raw);
    };
    window.MacbidBrowserState.updateItemMetadata(product.identity, {
      max_bid: parseOptional('#plan-max-bid'),
      max_all_in: parseOptional('#plan-max-all-in'),
      status: detailContent.querySelector('#plan-status')?.value || '',
      tags: (detailContent.querySelector('#plan-tags')?.value || '').split(',').map((v) => v.trim()).filter(Boolean),
      note: detailContent.querySelector('#plan-note')?.value?.trim() || '',
    });
    const button = event.currentTarget;
    button.textContent = 'Saved ✓';
    setTimeout(() => openDetails(row), 450);
    render();
  });
  detailContent.querySelector('#detail-watch')?.addEventListener('click', () => {
    toggleWatch(product.identity);
    dialog.close();
  });
  dialog.showModal();
}

function render() {
  if (!state.catalog) return;
  const allRows = rows();
  $('#result-count').textContent = allRows.length.toLocaleString();
  grid.replaceChildren();
  const fragment = document.createDocumentFragment();
  allRows.slice(0, state.visible).forEach((row) => fragment.append(renderCard(row)));
  if (!allRows.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'No active items match these filters.';
    fragment.append(empty);
  }
  grid.append(fragment);
  $('#load-more').hidden = state.visible >= allRows.length;
  $('#watch-toggle').classList.toggle('active', state.watchOnly);
  $('#watch-toggle').textContent = state.watchOnly ? '★ Watchlist' : '☆ Watchlist';
}

function resetVisible() {
  state.visible = 160;
  render();
}

async function loadCatalog() {
  const response = await fetch('catalog.json', { cache: 'no-store' });
  if (!response.ok) throw new Error(`Catalog HTTP ${response.status}`);
  state.catalog = await response.json();
  const categories = [...new Set(state.catalog.products.map((p) => p.category).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const select = $('#category');
  for (const value of categories) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
  const generated = new Date(state.catalog.generated_epoch_utc * 1000).toLocaleString();
  const tax = Number(state.catalog.sales_tax_rate || 0) * 100;
  const verified = Number(state.catalog.market_value_count || 0);
  const stale = Number(state.catalog.stale_market_value_count || 0);
  $('#catalog-meta').textContent = `${state.catalog.product_count.toLocaleString()} products · ${state.catalog.lot_count.toLocaleString()} active lots · ${verified} market-verified${stale ? ` · ${stale} stale` : ''} · ${Number(state.catalog.unverified_market_value_count ?? Math.max(0, state.catalog.product_count - verified - stale))} unverified · est. tax ${tax.toFixed(2)}% · updated ${generated}`;
  const historical = state.catalog.historical_acquisition;
  if (historical) $('#catalog-meta').textContent += ` · history: ${Number(historical.complete_scan_count || 0)} complete scans · ${Number(historical.complete_days || 0)} hourly-covered days · ${Number(historical.prospective?.verified_sold || 0)} verified closes · ${Number(historical.recovered_legacy_scope?.verified_sold || 0)} legacy sold · ${Number(historical.recovered_legacy_scope?.unresolved || 0)} legacy unresolved`;
  render();
}

$('#search').addEventListener('input', (event) => { state.query = event.target.value.trim().toLowerCase(); resetVisible(); });
$('#category').addEventListener('change', (event) => { state.category = event.target.value; resetVisible(); });
$('#condition').addEventListener('change', (event) => { state.condition = event.target.value; resetVisible(); });
$('#closes-within').addEventListener('change', (event) => { state.closesWithin = event.target.value ? Number(event.target.value) : null; resetVisible(); });
$('#min-retail').addEventListener('input', (event) => { state.minRetail = event.target.value ? Number(event.target.value) : null; event.target.dataset.huntDefault = ''; resetVisible(); });
$('#max-total').addEventListener('input', (event) => { state.maxTotal = event.target.value ? Number(event.target.value) : null; resetVisible(); });
$('#no-bidders').addEventListener('change', (event) => { state.noBidders = event.target.checked; resetVisible(); });
$('#watch-toggle').addEventListener('click', () => { state.watchOnly = !state.watchOnly; resetVisible(); });
$('#load-more').addEventListener('click', () => { state.visible += 160; render(); });
$('#dialog-close').addEventListener('click', () => dialog.close());

document.querySelectorAll('.tab').forEach((button) => button.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach((tab) => tab.classList.remove('active'));
  button.classList.add('active');
  state.sort = button.dataset.sort;
  resetVisible();
}));

$('#clear-filters').addEventListener('click', () => {
  state.query = '';
  state.category = '';
  state.condition = '';
  state.closesWithin = null;
  state.minRetail = null;
  state.maxTotal = null;
  state.noBidders = false;
  state.watchOnly = false;
  $('#search').value = '';
  $('#category').value = '';
  $('#condition').value = '';
  $('#closes-within').value = '';
  $('#min-retail').value = '';
  $('#min-retail').dataset.huntDefault = '';
  $('#max-total').value = '';
  $('#no-bidders').checked = false;
  resetVisible();
});

setInterval(() => {
  document.querySelectorAll('[data-close]').forEach((el) => { el.textContent = closeText(el.dataset.close); });
}, 30_000);

loadCatalog().catch((error) => {
  $('#catalog-meta').textContent = `Catalog failed to load: ${error.message}`;
  grid.innerHTML = '<div class="empty">Could not load the current catalog.</div>';
});
