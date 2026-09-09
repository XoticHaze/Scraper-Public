(() => {
  const topActions = document.querySelector('.top-actions');
  if (!topActions) return;

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'ghost';
  button.id = 'app-actions-open';
  button.textContent = 'App actions';
  topActions.prepend(button);

  const dialog = document.createElement('dialog');
  dialog.id = 'app-actions-dialog';
  dialog.innerHTML = `
    <button class="dialog-close" id="app-actions-close" aria-label="Close" type="button">×</button>
    <div class="action-center">
      <div class="action-center-head">
        <p class="eyebrow">REPO APP CONTROL</p>
        <h2>App actions</h2>
        <p class="muted">Allowed actions declared by this application. Direct one-tap execution will use the same contract once the authenticated control bridge is enabled.</p>
      </div>
      <div id="action-center-state" class="muted">Loading actions…</div>
      <div id="action-center-list" class="action-center-list"></div>
      <div class="action-center-note">
        <strong>Current execution mode</strong>
        <p class="muted">GitHub authenticated fallback. The public page contains no GitHub token or MAC.BID credential.</p>
      </div>
    </div>`;
  document.body.append(dialog);

  const list = dialog.querySelector('#action-center-list');
  const state = dialog.querySelector('#action-center-state');

  function riskLabel(risk) {
    return ({
      none: 'Navigation',
      read_only_compute: 'Read-only compute',
    })[risk] || String(risk || 'Action').replaceAll('_', ' ');
  }

  function renderAction(action) {
    const row = document.createElement('article');
    row.className = 'action-card';

    const copy = document.createElement('div');
    copy.className = 'action-card-copy';
    const title = document.createElement('strong');
    title.textContent = action.label || action.id;
    const desc = document.createElement('p');
    desc.className = 'muted';
    desc.textContent = action.description || '';
    const meta = document.createElement('span');
    meta.className = 'action-meta';
    meta.textContent = riskLabel(action.risk);
    copy.append(title, desc, meta);

    const link = document.createElement('a');
    link.className = 'action-run';
    link.href = action.fallback_url || '#';
    link.target = '_blank';
    link.rel = 'noreferrer';
    link.textContent = action.kind === 'workflow' ? 'Open to run ↗' : 'Open ↗';
    if (!action.fallback_url) {
      link.removeAttribute('href');
      link.setAttribute('aria-disabled', 'true');
      link.textContent = 'Unavailable';
    }

    row.append(copy, link);
    return row;
  }

  async function loadActions() {
    try {
      const response = await fetch('actions.json', { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const manifest = await response.json();
      list.replaceChildren();
      for (const action of manifest.actions || []) list.append(renderAction(action));
      state.textContent = `${(manifest.actions || []).length} declared actions · ${manifest.execution_mode || 'fallback'}`;
    } catch (error) {
      state.textContent = `Action manifest unavailable: ${error.message}`;
    }
  }

  button.addEventListener('click', () => {
    dialog.showModal();
    loadActions();
  });
  dialog.querySelector('#app-actions-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close();
  });
})();
