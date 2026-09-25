(() => {
  const api = window.MacbidBrowserState;
  const topActions = document.querySelector('.top-actions');
  if (!api || !topActions) return;

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'ghost';
  button.id = 'browser-profile-open';
  button.textContent = 'Profile';
  topActions.prepend(button);

  const dialog = document.createElement('dialog');
  dialog.id = 'browser-profile-dialog';
  dialog.innerHTML = `
    <button class="dialog-close" id="browser-profile-close" aria-label="Close" type="button">×</button>
    <div class="action-center">
      <div class="action-center-head">
        <p class="eyebrow">BROWSER-LOCAL IDENTITY</p>
        <h2>Browser profile</h2>
        <p class="muted">Personal scope and watchlist metadata stay in this browser. The public catalog and Pages source remain location-neutral.</p>
      </div>
      <label>Location label
        <input id="browser-profile-location-label" type="text" maxlength="80" placeholder="Optional, e.g. San Antonio" />
      </label>
      <label>Preferred locations
        <input id="browser-profile-locations" type="text" maxlength="240" placeholder="Comma-separated location names" />
      </label>
      <label>Preferred conditions
        <input id="browser-profile-conditions" type="text" maxlength="160" placeholder="LIKE NEW, OPEN BOX" />
      </label>
      <div class="detail-actions">
        <button id="browser-profile-use-catalog" type="button">Use current catalog scope</button>
        <button id="browser-profile-save" class="primary" type="button">Save locally</button>
      </div>
      <p id="browser-profile-status" class="muted"></p>
    </div>`;
  document.body.append(dialog);

  const locationLabel = dialog.querySelector('#browser-profile-location-label');
  const locations = dialog.querySelector('#browser-profile-locations');
  const conditions = dialog.querySelector('#browser-profile-conditions');
  const status = dialog.querySelector('#browser-profile-status');

  function loadForm() {
    const profile = api.getProfile();
    locationLabel.value = profile.location_label || '';
    locations.value = (profile.preferred_locations || []).join(', ');
    conditions.value = (profile.preferred_conditions || []).join(', ');
    status.textContent = 'Stored only in this browser/profile.';
  }

  function values(value) {
    return String(value || '').split(',').map((part) => part.trim()).filter(Boolean);
  }

  button.addEventListener('click', () => {
    loadForm();
    dialog.showModal();
  });

  dialog.querySelector('#browser-profile-save').addEventListener('click', () => {
    api.updateProfile({
      location_label: locationLabel.value,
      preferred_locations: values(locations.value),
      preferred_conditions: values(conditions.value),
    });
    status.textContent = 'Saved locally ✓';
    window.dispatchEvent(new CustomEvent('macbid-browser-profile-changed'));
  });

  dialog.querySelector('#browser-profile-use-catalog').addEventListener('click', () => {
    const catalogLocations = window.MACBID_CATALOG?.locations || [];
    locations.value = catalogLocations.join(', ');
    if (!locationLabel.value.trim() && catalogLocations.length) {
      locationLabel.value = catalogLocations.join(' + ');
    }
    status.textContent = catalogLocations.length
      ? 'Current catalog scope loaded. Save locally to keep it with this browser identity.'
      : 'This catalog does not publish a location scope.';
  });

  dialog.querySelector('#browser-profile-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close();
  });
})();
