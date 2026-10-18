(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const money = (value) => value == null ? 'Unknown' : new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD'
  }).format(Number(value));
  const create = (tag, className, content) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content != null) node.textContent = String(content);
    return node;
  };
  let catalog = null;

  function card(product) {
    const el = create('article', 'card');
    const image = create('div', 'image');
    if (product.image_url && /^https:\/\//.test(product.image_url)) {
      const img = document.createElement('img');
      img.src = product.image_url;
      img.alt = '';
      img.loading = 'lazy';
      img.referrerPolicy = 'no-referrer';
      image.appendChild(img);
    }
    el.appendChild(image);
    const body = create('div', 'body');
    const tags = create('div', 'tags');
    for (const name of [product.condition, ...(product.focus || [])]) {
      tags.appendChild(create('span', 'tag', name.replaceAll('_', ' ')));
    }
    body.appendChild(tags);
    body.appendChild(create('h2', '', product.title));
    body.appendChild(create('p', 'sub', [product.vendor, product.category].filter(Boolean).join(' · ')));
    const metrics = create('div', 'metrics');
    for (const [label, value] of [
      ['Price', money(product.price)],
      ['Est. all-in', money(product.estimated_all_in)],
      ['Seller claimed discount', product.seller_stated_discount_pct == null ? 'Unverified' : product.seller_stated_discount_pct + '% (unverified)'],
    ]) {
      const box = create('div', 'metric');
      box.appendChild(create('small', '', label));
      box.appendChild(create('strong', '', value));
      metrics.appendChild(box);
    }
    body.appendChild(metrics);
    const link = create('a', 'merchant', 'Verify at merchant ↗');
    const href = String(product.url || '');
    if (/^https:\/\/paotexas\.com\/products\/[a-z0-9-]+$/.test(href)) {
      link.href = href;
      link.target = '_blank';
      link.rel = 'noreferrer noopener';
      body.appendChild(link);
    }
    el.appendChild(body);
    return el;
  }

  function render() {
    if (!catalog) return;
    const query = $('search').value.trim().toLowerCase();
    const focus = $('focus').value;
    const focusedOnly = $('focused').checked;
    const limit = Number($('max-cost').value || 0);
    const products = (catalog.products || []).filter((item) => {
      if (focusedOnly && !(item.focus || []).length) return false;
      if (focus && !(item.focus || []).includes(focus)) return false;
      if (limit > 0 && Number(item.estimated_all_in) > limit) return false;
      if (query && ![item.title, item.vendor, item.category].join(' ').toLowerCase().includes(query)) return false;
      return true;
    });
    const sort = $('sort').value;
    if (sort === 'price') {
      products.sort((a, b) => a.estimated_all_in - b.estimated_all_in);
    } else if (sort === 'discount') {
      products.sort((a, b) => (b.seller_stated_discount_pct ?? -1) - (a.seller_stated_discount_pct ?? -1));
    } else {
      products.sort((a, b) => b.score - a.score || a.estimated_all_in - b.estimated_all_in);
    }
    const grid = $('grid');
    grid.replaceChildren(...products.slice(0, 150).map(card));
    $('count').textContent = products.length.toLocaleString('en-US');
    $('empty').hidden = products.length > 0;
  }

  async function load() {
    try {
      const response = await fetch('paotexas-catalog.json?t=' + Date.now(), { cache: 'no-store' });
      if (!response.ok) throw new Error('No published source snapshot (HTTP ' + response.status + ')');
      const data = await response.json();
      if (data.schema !== 'scraper-storefront-catalog-v1' ||
          data.source_type !== 'buy_it_now_not_hibid_auction' ||
          !Array.isArray(data.products) || !data.product_count) {
        throw new Error('Source is missing or not verified');
      }
      const age = (Date.now() - Date.parse(data.observed_at)) / 3600000;
      if (!Number.isFinite(age) || age < 0) throw new Error('Invalid source observation timestamp');
      catalog = data;
      $('health').textContent =
        (age > 12 ? 'STALE snapshot, verify all prices · ' : 'Source snapshot · ') +
        data.product_count + ' items · ' + data.focused_count + ' focused · observed ' +
        new Date(data.observed_at).toLocaleString('en-US') +
        ' · source age ' + age.toFixed(1) + ' h';
      for (const id of ['search', 'focus', 'sort', 'max-cost', 'focused']) $(id).addEventListener('input', render);
      render();
    } catch (error) {
      $('health').textContent = 'NO VERIFIED STOREFRONT SNAPSHOT · ' + error.message;
      $('grid').replaceChildren();
      $('count').textContent = '0';
      $('empty').hidden = false;
    }
  }
  load();
})();
