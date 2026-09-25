(() => {
  const STATE_KEY = 'macbid-browser-state-v1';
  const LEGACY_WATCHLIST_KEY = 'macbid-hunt-watchlist';

  function freshState() {
    return {
      schema: 'macbid-browser-state-v1',
      version: 1,
      profile: {
        location_label: '',
        preferred_locations: [],
        preferred_conditions: [],
        default_sort: '',
      },
      watchlists: {
        default: { id: 'default', name: 'Watchlist', items: [] },
      },
      items: {},
      updated_at: null,
    };
  }

  function normalizeId(value) {
    return String(value || '').trim();
  }

  function load() {
    let state = freshState();
    try {
      const stored = JSON.parse(localStorage.getItem(STATE_KEY) || 'null');
      if (stored && stored.schema === 'macbid-browser-state-v1') {
        state = {
          ...state,
          ...stored,
          profile: { ...state.profile, ...(stored.profile || {}) },
          watchlists: { ...state.watchlists, ...(stored.watchlists || {}) },
          items: { ...(stored.items || {}) },
        };
      }
    } catch {}

    try {
      const legacy = JSON.parse(localStorage.getItem(LEGACY_WATCHLIST_KEY) || '[]');
      const current = new Set(state.watchlists.default?.items || []);
      for (const raw of Array.isArray(legacy) ? legacy : []) {
        const id = normalizeId(raw);
        if (id) current.add(id);
      }
      state.watchlists.default = {
        ...(state.watchlists.default || {}),
        id: 'default',
        name: state.watchlists.default?.name || 'Watchlist',
        items: [...current],
      };
    } catch {}

    return state;
  }

  let state = load();

  function persist() {
    state.updated_at = new Date().toISOString();
    localStorage.setItem(STATE_KEY, JSON.stringify(state));
    localStorage.setItem(
      LEGACY_WATCHLIST_KEY,
      JSON.stringify(state.watchlists.default?.items || []),
    );
  }

  function watchlistSet(listId = 'default') {
    return new Set(state.watchlists[listId]?.items || []);
  }

  function replaceWatchlist(items, listId = 'default') {
    const id = normalizeId(listId) || 'default';
    const unique = [...new Set((items || []).map(normalizeId).filter(Boolean))];
    state.watchlists[id] = {
      ...(state.watchlists[id] || {}),
      id,
      name: state.watchlists[id]?.name || (id === 'default' ? 'Watchlist' : id),
      items: unique,
    };
    const now = new Date().toISOString();
    for (const identity of unique) {
      state.items[identity] = {
        ...(state.items[identity] || {}),
        updated_at: now,
        added_at: state.items[identity]?.added_at || now,
      };
    }
    persist();
    return watchlistSet(id);
  }

  function toggleWatch(identity, listId = 'default') {
    const id = normalizeId(identity);
    if (!id) return false;
    const items = watchlistSet(listId);
    if (items.has(id)) items.delete(id);
    else items.add(id);
    replaceWatchlist([...items], listId);
    return items.has(id);
  }

  function createWatchlist(name) {
    const label = String(name || '').trim();
    if (!label) throw new Error('watchlist name required');
    const base = label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'list';
    let id = base;
    let suffix = 2;
    while (state.watchlists[id]) id = `${base}-${suffix++}`;
    state.watchlists[id] = { id, name: label, items: [] };
    persist();
    return { ...state.watchlists[id] };
  }

  function renameWatchlist(listId, name) {
    const id = normalizeId(listId);
    const label = String(name || '').trim();
    if (!state.watchlists[id]) throw new Error('watchlist not found');
    if (!label) throw new Error('watchlist name required');
    state.watchlists[id].name = label;
    persist();
    return { ...state.watchlists[id] };
  }

  function deleteWatchlist(listId) {
    const id = normalizeId(listId);
    if (!id || id === 'default') throw new Error('default watchlist cannot be deleted');
    delete state.watchlists[id];
    persist();
  }

  function updateProfile(patch) {
    const next = { ...(patch || {}) };
    if ('preferred_locations' in next) {
      next.preferred_locations = [...new Set((next.preferred_locations || []).map(String).map((v) => v.trim()).filter(Boolean))];
    }
    if ('preferred_conditions' in next) {
      next.preferred_conditions = [...new Set((next.preferred_conditions || []).map(String).map((v) => v.trim()).filter(Boolean))];
    }
    if ('location_label' in next) next.location_label = String(next.location_label || '').trim();
    state.profile = { ...state.profile, ...next };
    persist();
    return { ...state.profile };
  }

  function updateItemMetadata(identity, patch) {
    const id = normalizeId(identity);
    if (!id) throw new Error('item identity required');
    const allowed = ['note', 'tags', 'max_bid', 'max_all_in', 'status'];
    const next = {};
    for (const key of allowed) {
      if (Object.prototype.hasOwnProperty.call(patch || {}, key)) next[key] = patch[key];
    }
    if (Array.isArray(next.tags)) {
      next.tags = [...new Set(next.tags.map(String).map((v) => v.trim()).filter(Boolean))];
    }
    state.items[id] = {
      ...(state.items[id] || {}),
      ...next,
      updated_at: new Date().toISOString(),
    };
    persist();
    return { ...state.items[id] };
  }

  function locationLabel() {
    if (state.profile.location_label) return state.profile.location_label;
    const locations = state.profile.preferred_locations || [];
    return locations.length ? locations.join(' + ') : '';
  }

  function snapshot() {
    return JSON.parse(JSON.stringify(state));
  }

  window.MacbidBrowserState = Object.freeze({
    key: STATE_KEY,
    snapshot,
    watchlistSet,
    replaceWatchlist,
    toggleWatch,
    createWatchlist,
    renameWatchlist,
    deleteWatchlist,
    listWatchlists: () => Object.values(state.watchlists).map((row) => ({ ...row, items: [...(row.items || [])] })),
    getProfile: () => ({ ...state.profile, preferred_locations: [...(state.profile.preferred_locations || [])], preferred_conditions: [...(state.profile.preferred_conditions || [])] }),
    updateProfile,
    updateItemMetadata,
    getItemMetadata: (identity) => ({ ...(state.items[normalizeId(identity)] || {}) }),
    locationLabel,
    exportJson: () => JSON.stringify(state, null, 2),
  });
})();
