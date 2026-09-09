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
        <p class="muted">Allowed actions declared by this application. The public page never receives a GitHub token, GitHub App private key, or MAC.BID credential.</p>
      </div>
      <div id="action-center-state" class="muted">Loading actions…</div>
      <div id="action-center-list" class="action-center-list"></div>
      <div class="action-center-note" id="action-center-note">
        <strong>Current execution mode</strong>
        <p class="muted" id="action-center-mode">Loading…</p>
      </div>
    </div>`;
  document.body.append(dialog);

  const list = dialog.querySelector('#action-center-list');
  const state = dialog.querySelector('#action-center-state');
  const modeCopy = dialog.querySelector('#action-center-mode');

  function riskLabel(risk) {
    return ({
      none: 'Navigation',
      read_only_compute: 'Read-only compute',
    })[risk] || String(risk || 'Action').replaceAll('_', ' ');
  }

  function bridgeBase(manifest) {
    const value = manifest?.control_bridge?.enabled ? manifest?.control_bridge?.endpoint : null;
    return value ? String(value).replace(/\/$/, '') : null;
  }

  async function runBridgeAction(action, manifest, trigger, statusEl) {
    const base = bridgeBase(manifest);
    if (!base) return;
    const requestId = crypto.randomUUID ? crypto.randomUUID() : `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    trigger.disabled = true;
    statusEl.textContent = 'Submitting…';
    try {
      const response = await fetch(`${base}/v1/actions`, {
        method: 'POST',
        mode: 'cors',
        credentials: 'include',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          app_id: manifest.app_id,
          action_id: action.id,
          request_id: requestId,
          inputs: {},
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.accepted) throw new Error(payload.error || `HTTP ${response.status}`);
      statusEl.textContent = 'Queued ✓';
      if (payload.operator_url) {
        const link = document.createElement('a');
        link.href = payload.operator_url;
        link.target = '_blank';
        link.rel = 'noreferrer';
        link.textContent = 'View run ↗';
        statusEl.append(' · ', link);
      }
    } catch (error) {
      statusEl.textContent = `Could not run: ${error.message}`;
    } finally {
      trigger.disabled = false;
    }
  }

  function renderAction(action, manifest) {
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
    const statusEl = document.createElement('div');
    statusEl.className = 'action-card-status muted';
    copy.append(title, desc, meta, statusEl);

    const useBridge = action.kind === 'workflow' && Boolean(bridgeBase(manifest));
    let control;
    if (useBridge) {
      control = document.createElement('button');
      control.type = 'button';
      control.className = 'action-run';
      control.textContent = 'Run now';
      control.addEventListener('click', () => runBridgeAction(action, manifest, control, statusEl));
    } else {
      control = document.createElement('a');
      control.className = 'action-run';
      control.href = action.fallback_url || '#';
      control.target = '_blank';
      control.rel = 'noreferrer';
      control.textContent = action.kind === 'workflow' ? 'Open to run ↗' : 'Open ↗';
      if (!action.fallback_url) {
        control.removeAttribute('href');
        control.setAttribute('aria-disabled', 'true');
        control.textContent = 'Unavailable';
      }
    }

    row.append(copy, control);
    return row;
  }

  async function loadActions() {
    try {
      const response = await fetch('actions.json', { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const manifest = await response.json();
      list.replaceChildren();
      for (const action of manifest.actions || []) list.append(renderAction(action, manifest));
      const bridge = bridgeBase(manifest);
      state.textContent = `${(manifest.actions || []).length} declared actions · ${manifest.execution_mode || 'fallback'}`;
      if (bridge) {
        modeCopy.innerHTML = `Authenticated control bridge enabled. <a href="${bridge}/health" target="_blank" rel="noreferrer">Connect / health ↗</a>`;
      } else {
        modeCopy.textContent = 'GitHub authenticated fallback. Workflow actions open GitHub until the private control bridge is deployed and enabled.';
      }
    } catch (error) {
      state.textContent = `Action manifest unavailable: ${error.message}`;
      modeCopy.textContent = 'Unavailable';
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
