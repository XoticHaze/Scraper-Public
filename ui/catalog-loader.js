(() => {
  const nativeFetch = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = (input, init) => {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if ((url === 'catalog.json' || url.endsWith('/catalog.json')) && window.MACBID_CATALOG) {
      return Promise.resolve(new Response(JSON.stringify(window.MACBID_CATALOG), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }));
    }
    if (!nativeFetch) return Promise.reject(new Error('Fetch unavailable'));
    return nativeFetch(input, init);
  };
})();
