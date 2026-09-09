(() => {
  const search = document.querySelector('#search');
  const controls = document.querySelector('.controls');
  const topbar = document.querySelector('.topbar');

  if (!search || !controls || !topbar) return;

  state.hunt = state.hunt || '';
  const baseProductMatchesSearch = productMatchesSearch;
  productMatchesSearch = function enhancedProductMatch(product) {
    if (state.hunt && !(product.hunt_ids || []).includes(state.hunt)) return false;
    return baseProductMatchesSearch(product);
  };

  function syncHuntButtons() {
    document.querySelectorAll('.quick-chip').forEach((button) => {
      button.classList.toggle('active', button.dataset.hunt === state.hunt);
    });
  }

  function setHunt(value) {
    const hunt = String(value || '').trim();
    state.hunt = hunt;
    const url = new URL(window.location.href);
    if (hunt) url.searchParams.set('hunt', hunt);
    else url.searchParams.delete('hunt');
    history.replaceState(null, '', url);
    syncHuntButtons();
    resetVisible();
  }

  function setQuery(value) {
    const query = String(value || '').trim();
    search.value = query;
    state.query = query.toLowerCase();
    const url = new URL(window.location.href);
    if (query) url.searchParams.set('q', query);
    else url.searchParams.delete('q');
    history.replaceState(null, '', url);
    resetVisible();
  }

  function installQuickBar() {
    if (document.querySelector('.quick-bar')) return;
    const profiles = (state.catalog?.hunt_profiles || []).filter((profile) => Number(profile.count || 0) > 0);
    if (!profiles.length) return;
    const bar = document.createElement('div');
    bar.className = 'quick-bar';
    const label = document.createElement('span');
    label.className = 'quick-label';
    label.textContent = 'Hunts';
    bar.append(label);

    for (const profile of profiles) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'quick-chip';
      button.dataset.hunt = profile.id;
      button.title = (profile.verification || []).length
        ? `Verification: ${(profile.verification || []).join(', ')}`
        : profile.label;
      button.textContent = `${profile.label} · ${Number(profile.count).toLocaleString()}`;
      button.addEventListener('click', () => setHunt(state.hunt === profile.id ? '' : profile.id));
      bar.append(button);
    }
    controls.querySelector('.search-wrap')?.after(bar);
    syncHuntButtons();
  }

  function activeFilterCount() {
    return [state.hunt, state.category, state.condition, state.closesWithin, state.maxTotal, state.noBidders].filter(Boolean).length;
  }

  function updateFilterToggle() {
    const button = document.querySelector('#mobile-filter-toggle');
    if (!button) return;
    const count = activeFilterCount();
    button.textContent = count ? `Filters · ${count} active` : 'Filters';
  }

  function installMobileFilters() {
    if (document.querySelector('#mobile-filter-toggle')) return;
    const button = document.createElement('button');
    button.id = 'mobile-filter-toggle';
    button.className = 'mobile-filter-toggle';
    button.type = 'button';
    button.setAttribute('aria-expanded', 'false');
    button.textContent = 'Filters';
    button.addEventListener('click', () => {
      const open = controls.classList.toggle('filters-open');
      button.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    controls.querySelector('.view-tabs')?.after(button);

    ['#category', '#condition', '#closes-within', '#max-total', '#no-bidders'].forEach((selector) => {
      document.querySelector(selector)?.addEventListener('change', updateFilterToggle);
      document.querySelector(selector)?.addEventListener('input', updateFilterToggle);
    });
  }

  function nextScheduleText() {
    const now = new Date();
    const current = now.getMinutes();
    let delta;
    if (current < 17) delta = 17 - current;
    else if (current < 47) delta = 47 - current;
    else delta = 60 - current + 17;
    if (delta <= 1) return 'Auto refresh due now';
    return `Next auto refresh ~${delta}m`;
  }

  function freshness(ageMinutes) {
    if (ageMinutes < 45) return ['fresh', 'Fresh snapshot'];
    if (ageMinutes < 90) return ['warn', 'Snapshot aging'];
    return ['stale', 'Snapshot stale'];
  }

  function installStatusStrip() {
    if (document.querySelector('.app-status')) return;
    const strip = document.createElement('section');
    strip.className = 'app-status';
    strip.innerHTML = `
      <div class="status-main">
        <span class="status-badge"><span class="status-dot"></span><strong id="snapshot-health">Loading snapshot</strong></span>
        <span id="snapshot-age" class="status-copy">—</span>
        <span id="next-refresh" class="status-copy">—</span>
        <span class="status-scope">San Antonio · Like New + Open Box</span>
      </div>
      <div class="status-links">
        <a href="https://github.com/XoticHaze/Scraper-Public/actions" target="_blank" rel="noreferrer">Actions ↗</a>
        <a href="https://github.com/XoticHaze/Scraper-Public" target="_blank" rel="noreferrer">Source ↗</a>
      </div>`;
    topbar.after(strip);
  }

  function updateStatus() {
    if (!state.catalog) return;
    const generated = Number(state.catalog.generated_epoch_utc || 0);
    if (!generated) return;
    const ageMinutes = Math.max(0, Math.floor((Date.now() / 1000 - generated) / 60));
    const [healthClass, healthLabel] = freshness(ageMinutes);
    const strip = document.querySelector('.app-status');
    if (!strip) return;
    strip.classList.remove('fresh', 'warn', 'stale');
    strip.classList.add(healthClass);
    document.querySelector('#snapshot-health').textContent = healthLabel;
    document.querySelector('#snapshot-age').textContent = ageMinutes < 1 ? 'Updated just now' : `Updated ${ageMinutes}m ago`;
    document.querySelector('#next-refresh').textContent = nextScheduleText();
  }

  installStatusStrip();
  installMobileFilters();

  if (window.matchMedia('(max-width: 560px)').matches) {
    search.placeholder = 'Search products, brands…';
  }

  const initialQuery = new URL(window.location.href).searchParams.get('q');
  const initialHunt = new URL(window.location.href).searchParams.get('hunt');
  if (initialQuery) setQuery(initialQuery);
  if (initialHunt) state.hunt = initialHunt;

  search.addEventListener('input', () => {
    const url = new URL(window.location.href);
    const query = search.value.trim();
    if (query) url.searchParams.set('q', query);
    else url.searchParams.delete('q');
    history.replaceState(null, '', url);
  });

  document.querySelector('#clear-filters')?.addEventListener('click', () => {
    const url = new URL(window.location.href);
    url.searchParams.delete('q');
    url.searchParams.delete('hunt');
    history.replaceState(null, '', url);
    state.hunt = '';
    syncHuntButtons();
    controls.classList.remove('filters-open');
    document.querySelector('#mobile-filter-toggle')?.setAttribute('aria-expanded', 'false');
    setTimeout(updateFilterToggle, 0);
  });

  const waitForCatalog = setInterval(() => {
    if (!state.catalog) return;
    clearInterval(waitForCatalog);
    installQuickBar();
    if (initialHunt && (state.catalog.hunt_profiles || []).some((profile) => profile.id === initialHunt)) {
      setHunt(initialHunt);
    }
    updateStatus();
    updateFilterToggle();
  }, 100);
  setInterval(updateStatus, 30_000);
})();
