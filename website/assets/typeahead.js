/**
 * Generic "type a name, pick from a dropdown" field - every place that
 * references real Nextcloud data by id (a user, a board, a stack, a
 * calendar, a card) uses this same widget instead of asking someone to
 * know and type the underlying id directly. Shared as a plain global
 * (loaded before builder.js/test_run.js, no module system in use here)
 * since it's now used by more than one page, not just the step builder.
 *
 * config:
 *   value        - initial text
 *   setValue(v)  - called on every keystroke *and* on picking a result,
 *                  so pasting a known id works even if nothing is ever
 *                  picked from the dropdown
 *   placeholder
 *   loadOptions(query) -> [{id, label}] | Promise<[{id, label}]>
 *   minChars     - don't call loadOptions below this length (default 0)
 *   debounceMs   - delay before calling loadOptions (default 0 - used
 *                  for the already-fetched, small lists; user search sets
 *                  this since it hits the network per keystroke)
 *   onPick(item) - optional, called only when a result is actually
 *                  clicked (e.g. to cascade-load a board's stacks)
 */
function renderTypeahead(config) {
  'use strict';

  const wrapper = document.createElement('div');
  wrapper.className = 'typeahead';

  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = config.placeholder || '';
  input.value = config.value || '';

  const resultsEl = document.createElement('div');
  resultsEl.className = 'typeahead-results';
  resultsEl.hidden = true;

  let debounceTimer = null;

  function showResults(items) {
    resultsEl.innerHTML = '';
    if (items.length === 0) {
      resultsEl.hidden = true;
      return;
    }
    items.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'typeahead-result';
      row.textContent = item.id === item.label ? item.label : item.label + ' (' + item.id + ')';
      row.addEventListener('click', () => {
        config.setValue(item.id);
        input.value = item.label;
        resultsEl.hidden = true;
        if (config.onPick) {
          config.onPick(item);
        }
      });
      resultsEl.appendChild(row);
    });
    resultsEl.hidden = false;
  }

  function runQuery() {
    const query = input.value.trim();
    if (query.length < (config.minChars || 0)) {
      resultsEl.hidden = true;
      return;
    }
    Promise.resolve(config.loadOptions(query)).then(showResults).catch(() => {
      // Non-fatal: the field still works as a plain text input even if
      // the lookup itself fails (unreachable instance, etc.).
    });
  }

  input.addEventListener('input', () => {
    config.setValue(input.value);
    resultsEl.hidden = true;
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    if (config.debounceMs) {
      debounceTimer = setTimeout(runQuery, config.debounceMs);
    } else {
      runQuery();
    }
  });

  // Shows the current matches as soon as the field is focused - the
  // "Vorauswahl" (preselection) is visible without typing anything first,
  // for an already-fetched list (boards/stacks/calendars: minChars 0).
  input.addEventListener('focus', () => {
    if (resultsEl.hidden) {
      runQuery();
    }
  });

  wrapper.appendChild(input);
  wrapper.appendChild(resultsEl);
  return wrapper;
}
