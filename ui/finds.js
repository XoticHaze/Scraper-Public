(() => {
  const catalog = window.MACBID_CATALOG;
  const research = window.MACBID_RESEARCH_FINDINGS || { findings: [] };
  const root = document.querySelector('#finds-sections');
  const nav = document.querySelector('#finds-nav');
  const meta = document.querySelector('#finds-meta');
  const status = document.querySelector('#finds-status');
  if (!catalog || !root || !nav) return;

  const priority = [
    '4k-projectors','curved-monitors','large-gaming-monitors','quality-speakers',
    'solar-panels','ptz-cameras-haos','smart-door-locks-haos','large-area-rugs',
    'tools','samsung-tablets','apple-devices','best-tech-deals','resale-watch'
  ];
  const profileMap = new Map((catalog.hunt_profiles || []).map((p) => [p.id, p]));
  const researchMap = new Map((research.findings || []).map((item) => [item.identity, item]));
  const watched = new Set(JSON.parse(localStorage.getItem('macbid-hunt-watchlist') || '[]'));
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const safeUrl = (value, hosts = null) => {
    try {
      const url = new URL(value);
      if (url.protocol !== 'https:') return '';
      if (hosts && !hosts.includes(url.hostname)) return '';
      return url.href;
    } catch { return ''; }
  };
  const money = (v) => Number.isFinite(Number(v)) ? `$${Number(v).toFixed(2)}` : '—';
  const lotAllIn = (lot) => Number(lot?.estimated_post_tax_total ?? lot?.estimated_all_in_total ?? lot?.estimated_pre_tax_total);
  const closeText = (epoch) => {
    const s = Number(epoch || 0) - Date.now() / 1000;
    if (s <= 0) return 'closed';
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m`;
    return `${(s / 3600).toFixed(s < 10800 ? 1 : 0)}h`;
  };
  const bestLot = (product) => [...(product.lots || [])].sort((a,b) => {
    const av = Number(a.deal_score || 0) - Number(a.unique_bidders || 0) * 2;
    const bv = Number(b.deal_score || 0) - Number(b.unique_bidders || 0) * 2;
    return bv - av;
  })[0];
  const scoreFor = (product, profileId) => {
    const lot = bestLot(product) || {};
    const semantic = Number(product.hunt_matches?.[profileId]?.score || 0);
    const researched = researchMap.has(product.identity) ? 12 : 0;
    return researched + semantic * 10 + Number(lot.deal_score || 0) - Number(lot.unique_bidders || 0) * 2;
  };
  const researchMarkup = (product) => {
    const finding = researchMap.get(product.identity);
    if (!finding) return '';
    const sourceLinks = (finding.sources || []).map((source) => {
      const url = safeUrl(source.url);
      return url ? `<a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(source.label || 'Source')} ↗</a>` : '';
    }).filter(Boolean).join(' · ');
    return `<div class="research-note">
      <div class="research-head"><span class="find-badge research">${esc(finding.status || 'RESEARCHED')}</span>${finding.model ? `<strong>${esc(finding.model)}</strong>` : ''}</div>
      <p>${esc(finding.note || '')}</p>
      ${sourceLinks ? `<div class="research-sources">${sourceLinks}</div>` : ''}
    </div>`;
  };
  const card = (product, profileId = '') => {
    const lot = bestLot(product) || {};
    const match = profileId ? (product.hunt_matches?.[profileId] || {}) : {};
    const article = document.createElement('article');
    article.className = 'find-card';
    const image = product.image_url || lot.image_url || lot.stock_image_url || '';
    const imageUrl = safeUrl(image);
    const haos = match.compatibility_gate === 'haos';
    const verify = (match.verification || []).map((v) => String(v).replaceAll('_',' ')).join(' · ');
    const lotUrl = safeUrl(lot.macbid_url, ['mac.bid','www.mac.bid']);
    article.innerHTML = `
      <div class="image-wrap">${imageUrl ? `<img loading="lazy" src="${esc(imageUrl)}" alt="">` : ''}</div>
      <div class="find-body">
        <div class="find-badges">
          <span class="find-badge">${esc(lot.condition || 'Unknown')}</span>
          ${haos ? '<span class="find-badge haos">HAOS VERIFY</span>' : ''}
          ${researchMap.has(product.identity) ? '<span class="find-badge research">RESEARCHED</span>' : ''}
          ${watched.has(product.identity) ? '<span class="find-badge">★ WATCHED</span>' : ''}
          ${Number(lot.unique_bidders || 0) === 0 ? '<span class="find-badge">0 bidders</span>' : ''}
        </div>
        <h3>${esc(product.name || 'Unnamed item')}</h3>
        <div class="find-metrics">
          <div class="find-metric"><span>Current bid</span><strong>${money(lot.current_bid)}</strong></div>
          <div class="find-metric"><span>Est. all-in</span><strong>${money(lotAllIn(lot))}</strong></div>
          <div class="find-metric"><span>MAC retail</span><strong>${money(lot.retail_price)}</strong></div>
          <div class="find-metric"><span>Closes</span><strong>${esc(closeText(lot.expected_closing_utc))}</strong></div>
        </div>
        ${researchMarkup(product)}
        ${verify ? `<div class="verify-line">Verify: ${esc(verify)}</div>` : ''}
        <div class="find-links">
          ${lotUrl ? `<a href="${esc(lotUrl)}" target="_blank" rel="noreferrer">Open lot ↗</a>` : ''}
          ${profileId ? `<a href="./?hunt=${encodeURIComponent(profileId)}">Open hunt →</a>` : '<a href="./">Open catalog →</a>'}
        </div>
      </div>`;
    return article;
  };

  function addSection({ id, label, products, subtitle, profileId = '', seeAll = '' }) {
    const anchor = document.createElement('a');
    anchor.className = 'quick-chip';
    anchor.href = `#${id}`;
    anchor.textContent = `${label} · ${products.length}`;
    nav.append(anchor);

    const section = document.createElement('section');
    section.className = 'finds-section';
    section.id = id;
    section.innerHTML = `<div class="finds-section-head"><div><h2>${esc(label)}</h2><p class="muted">${esc(subtitle)}</p></div>${seeAll ? `<a href="${esc(seeAll)}">See all ${products.length} →</a>` : ''}</div>`;
    const grid = document.createElement('div');
    grid.className = 'finds-grid';
    if (!products.length) grid.innerHTML = '<div class="empty-lane">No current candidates in this snapshot.</div>';
    else products.slice(0, 8).forEach((product) => grid.append(card(product, profileId)));
    section.append(grid);
    root.append(section);
  }

  const generated = Number(catalog.generated_epoch_utc || 0);
  const age = generated ? Math.max(0, Math.round(Date.now()/1000 - generated)) : null;
  const taxPct = Number(catalog.sales_tax_rate || 0) * 100;
  meta.textContent = `${Number(catalog.product_count || 0).toLocaleString()} products · ${Number(catalog.lot_count || 0).toLocaleString()} lots · ${researchMap.size} researched · est. tax ${taxPct.toFixed(2)}% · San Antonio`;
  status.textContent = age == null ? 'Snapshot age unknown' : age < 60 ? 'Updated just now' : `Updated ${Math.round(age/60)}m ago`;

  const watchedProducts = (catalog.products || []).filter((p) => watched.has(p.identity));
  watchedProducts.sort((a,b) => Number(bestLot(a)?.expected_closing_utc || Infinity) - Number(bestLot(b)?.expected_closing_utc || Infinity));
  addSection({
    id: 'my-watchlist', label: 'My Watchlist', products: watchedProducts,
    subtitle: watchedProducts.length ? 'Browser-saved items, ordered toward the nearest close.' : 'Star items in the main Hunt app and they will appear here.',
    seeAll: './',
  });

  const researchedProducts = (catalog.products || []).filter((p) => researchMap.has(p.identity));
  researchedProducts.sort((a,b) => scoreFor(b,'') - scoreFor(a,''));
  addSection({
    id: 'researched', label: 'Researched Finds', products: researchedProducts,
    subtitle: 'Items we have already model-checked, compatibility-checked, or otherwise investigated together. Current bids and estimated all-in costs still come from the latest scan.',
    seeAll: '',
  });

  for (const id of priority) {
    const profile = profileMap.get(id);
    if (!profile) continue;
    const products = (catalog.products || []).filter((p) => (p.hunt_ids || []).includes(id));
    products.sort((a,b) => scoreFor(b,id) - scoreFor(a,id));
    const resaleNote = id === 'resale-watch' ? ' · preliminary until real market value, liquidity, fees and net margin are verified' : '';
    addSection({
      id,
      label: profile.label,
      products,
      profileId: id,
      subtitle: `Top current discovery candidates${profile.compatibility_gate === 'haos' ? ' · HAOS compatibility must clear before recommendation' : ''}${resaleNote}.`,
      seeAll: `./?hunt=${encodeURIComponent(id)}`,
    });
  }
})();
