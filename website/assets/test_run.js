/**
 * Drives test_run.php's card picker - mounts a renderTypeahead() (see
 * assets/typeahead.js) fetching every card on the workflow's own board via
 * api_cards.php, and blocks submitting without an actual pick.
 */
(function () {
  'use strict';

  const errorEl = document.getElementById('error-banner');

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
  }

  function hideError() {
    errorEl.hidden = true;
  }

  async function fetchJSON(url) {
    const response = await fetch(url);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `Request to ${url} failed`);
    }
    return data;
  }

  function filterByTitle(items, query) {
    const q = query.trim().toLowerCase();
    return items
      .filter((item) => item.title.toLowerCase().includes(q))
      .map((item) => ({ id: String(item.id), label: item.title }));
  }

  const cardIdEl = document.getElementById('card-id');
  const cardFieldEl = document.getElementById('card-field');
  let cardsCache = null;

  async function loadCards(query) {
    if (!cardsCache) {
      const data = await fetchJSON(
        'api_cards.php?instance=' + encodeURIComponent(window.TEST_RUN_INSTANCE)
          + '&board_id=' + encodeURIComponent(window.TEST_RUN_BOARD_ID)
      );
      cardsCache = data.cards || [];
    }
    return filterByTitle(cardsCache, query);
  }

  cardFieldEl.className = '';
  cardFieldEl.innerHTML = '';
  cardFieldEl.appendChild(
    renderTypeahead({
      value: '',
      placeholder: 'Kartentitel eingeben',
      setValue: (value) => {
        cardIdEl.value = value;
      },
      loadOptions: async (query) => {
        try {
          return await loadCards(query);
        } catch (e) {
          showError(e.message);
          return [];
        }
      },
    })
  );

  document.getElementById('test-run-form').addEventListener('submit', (event) => {
    hideError();
    if (!/^\d+$/.test(cardIdEl.value.trim())) {
      event.preventDefault();
      showError('Bitte eine Karte aus der Liste auswählen.');
    }
  });
})();
