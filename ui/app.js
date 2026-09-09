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
  maxTotal: null,
  noBidders: false,
  watchOnly: false,
  visible: 160,
  watchlist: new Set(JSON.parse(localStorage.getItem('macbid-hunt-watchlist') || '[]')),
};

function money(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }) : '—';
}

function number(value) {
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

function saveWatchlist() {
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
    if (state.maxTotal !== null && Number(lot.estimated_pre_tax_total || Infinity) > state.maxTotal) return false;
    if (state.closesWithin !== null && (close === null || close > now + state.closesWithin * 3600)) return false;
    return true;
  });
}

function lotComparator(mode) {
  if (mode === 'value') {
    return (a, b) => Number(b.deal_score || -9999) - Number(a.deal_score || -9999) || Number(a.expected_closing_utc || Infinity) - Number(b.expected_closing_utc || Infinity);
  }
  if (mode === 'competition') {
    return (a, b) => Number(a.unique_bidders || 0) - Number(b.unique_bidders || 0) || Number(a.total_bids || 0) - Number(b.total_bids || 0) || Number(b.deal_score || -9999) - Number(a.deal_score || -9999);
  }
  if (mode === 'cost') {
    return (a, b) => Number(a.estimated_pre_tax_total || Infinity) - Number(b.estimated_pre_tax_total || Infinity) || Number(b.deal_score || -9999) - Number(a.deal_score || -9999);
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
  if (lots.length > 1) chips.append(chip(`${lots.length} lots`));
  title.textContent = product.name;
  brand.textContent = [product.brand, product.category].filter(Boolean).join(' · ');

  metrics.append(
    metric('Current bid', money(lot.current_bid)),
    metric('Est. pre-tax', money(lot.estimated_pre_tax_total), 'good'),
    metric('Stated retail', money(lot.retail_price || product.retail_price)),
    metric('Closes', closeText(lot.expected_closing_utc))
  );
  metrics.lastElementChild.querySelector('strong').dataset.close = lot.expected_closing_utc || '';

  const left = document.createElement('span');
  left.textContent = `${Number(lot.unique_bidders || 0)} bidders · ${Number(lot.total_bids || 0)} bids`;
  const right = document.createElement('span');
  right.textContent = `${pct(lot.stated_retail_discount_pct)} off`;
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

function verifiedMarkup(product, lot) {
  const status = product.market_price_status || lot.market_price_status || 'unverified';
  const verifiedNew = product.verified_new_price ?? lot.verified_new_price;
  const openBoxValue = product.realistic_open_box_value ?? lot.realistic_open_box_value;
  const verdict = product.verdict ?? lot.verdict;
  const maxBid = product.verified_max_bid ?? product.max_bid ?? lot.verified_max_bid ?? lot.max_bid;
  if (status === 'unverified' && verifiedNew == null && openBoxValue == null && verdict == null) {
    return `<div class="verify-box"><strong>Market verification</strong><p class="muted">Not verified yet. The current score uses MAC.BID catalog data only. External model/market-price validation will populate verified new price, realistic open-box value, verdict, and final max bid here.</p></div>`;
  }
  return `<div class="verify-box">
    <strong>Market verification</strong>
    <div class="cost-row"><span>Verified new price</span><strong>${money(verifiedNew)}</strong></div>
    <div class="cost-row"><span>Realistic open-box value</span><strong>${money(openBoxValue)}</strong></div>
    <div class="cost-row"><span>Verified discount</span><strong class="good">${pct(product.verified_discount_pct ?? lot.verified_discount_pct)}</strong></div>
    <div class="cost-row"><span>Verdict</span><strong>${verdict || '—'}</strong></div>
    <div class="cost-row total"><span>Final max bid</span><strong>${money(maxBid)}</strong></div>
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

function openDetails(row) {
  const { product, lot, lots } = row;
  const bid = Number(lot.current_bid || 0);
  const premium = bid * Number(state.catalog.buyer_premium_rate || 0.15);
  const fee = Number(state.catalog.lot_fee || 3);
  const image = lot.image_url || product.image_url || '';
  const altRows = [...product.lots]
    .filter((entry) => Number(entry.expected_closing_utc || 0) > Date.now() / 1000)
    .sort((a, b) => Number(a.expected_closing_utc || Infinity) - Number(b.expected_closing_utc || Infinity))
    .slice(0, 20)
    .map((entry) => `<div class="alt"><span>${escapeHtml(entry.condition || '')} · ${money(entry.current_bid)} · ${closeText(entry.expected_closing_utc)}</span><span>${Number(entry.unique_bidders || 0)} bidders</span><a href="${safeMacUrl(entry.macbid_url)}" target="_blank" rel="noreferrer">Open ↗</a></div>`)
    .join('');

  detailContent.innerHTML = `<div class="detail">
    <div class="detail-media">${image ? `<img src="${escapeHtml(image)}" alt="${escapeHtml(product.name)}">` : ''}</div>
    <div class="detail-body">
      <div class="chips"><span class="chip ${lot.condition === 'LIKE NEW' ? 'good' : 'warn'}">${escapeHtml(lot.condition)}</span><span class="chip">${escapeHtml(product.category || 'Uncategorized')}</span>${product.lot_count > 1 ? `<span class="chip">${product.lot_count} lots</span>` : ''}</div>
      <h2>${escapeHtml(product.name)}</h2>
      <p class="sub">${escapeHtml([product.brand, product.model, product.upc ? `UPC ${product.upc}` : null].filter(Boolean).join(' · '))}</p>
      <div class="cost-box">
        <div class="cost-row"><span>Current bid</span><strong>${money(bid)}</strong></div>
        <div class="cost-row"><span>Buyer premium (${(Number(state.catalog.buyer_premium_rate || .15) * 100).toFixed(0)}%)</span><strong>${money(premium)}</strong></div>
        <div class="cost-row"><span>Lot fee</span><strong>${money(fee)}</strong></div>
        <div class="cost-row total"><span>Estimated pre-tax total</span><strong>${money(lot.estimated_pre_tax_total)}</strong></div>
        <div class="cost-row"><span>MAC.BID stated retail</span><strong>${money(lot.retail_price || product.retail_price)}</strong></div>
        <div class="cost-row"><span>Stated-retail discount</span><strong class="good">${pct(lot.stated_retail_discount_pct)}</strong></div>
        <div class="cost-row"><span>Stated-retail savings</span><strong class="good">${money(lot.stated_retail_savings)}</strong></div>
        <div class="cost-row"><span>Provisional max bid</span><strong>${money(lot.provisional_max_bid)}</strong></div>
      </div>
      <p class="muted">Provisional ceiling is discovery-only until the exact model and real market price are verified.</p>
      ${verifiedMarkup(product, lot)}
      <div class="lot-box">
        <strong>Lot state</strong>
        <div class="cost-row"><span>Closes</span><strong data-close="${escapeHtml(lot.expected_closing_utc || '')}">${closeText(lot.expected_closing_utc)}</strong></div>
        <div class="cost-row"><span>Local close time</span><strong>${escapeHtml(localClose(lot.expected_closing_utc))}</strong></div>
        <div class="cost-row"><span>Competition</span><strong>${Number(lot.unique_bidders || 0)} bidders · ${Number(lot.total_bids || 0)} bids</strong></div>
        <div class="cost-row"><span>Deal discovery score</span><strong>${Number(lot.deal_score || 0).toFixed(1)}</strong></div>
      </div>
      ${product.lot_count > 1 ? `<div class="lot-box"><strong>Other active lots</strong><div class="alt-list">${altRows}</div></div>` : ''}
      <div class="detail-actions">
        <a class="primary-link" href="${safeMacUrl(lot.macbid_url)}" target="_blank" rel="noreferrer">View lot on MAC.BID ↗</a>
        <button id="detail-watch" type="button">${state.watchlist.has(product.identity) ? '★ Watching' : '☆ Add to watchlist'}</button>
      </div>
    </div>
  </div>`;
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
  $('#catalog-meta').textContent = `${state.catalog.product_count.toLocaleString()} products · ${state.catalog.lot_count.toLocaleString()} active lots · updated ${generated}`;
  render();
}

$('#search').addEventListener('input', (event) => { state.query = event.target.value.trim().toLowerCase(); resetVisible(); });
$('#category').addEventListener('change', (event) => { state.category = event.target.value; resetVisible(); });
$('#condition').addEventListener('change', (event) => { state.condition = event.target.value; resetVisible(); });
$('#closes-within').addEventListener('change', (event) => { state.closesWithin = event.target.value ? Number(event.target.value) : null; resetVisible(); });
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
  state.maxTotal = null;
  state.noBidders = false;
  state.watchOnly = false;
  $('#search').value = '';
  $('#category').value = '';
  $('#condition').value = '';
  $('#closes-within').value = '';
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
