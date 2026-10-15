/**
 * Drives test_run.php's card picker - a dropdown of every card on the
 * workflow's own board (via api_cards.php) - and asks for confirmation
 * before submitting.
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

  const cardIdEl = document.getElementById('card-id');
  const cardFieldEl = document.getElementById('card-field');

  // A plain dropdown of every card on the board (first one preselected), so
  // confirming a test run never requires typing a card title.
  (async function mountCardSelect() {
    try {
      const data = await fetchJSON(
        'api_cards.php?instance=' + encodeURIComponent(window.TEST_RUN_INSTANCE)
          + '&board_id=' + encodeURIComponent(window.TEST_RUN_BOARD_ID)
      );
      const cards = data.cards || [];
      cardFieldEl.className = '';
      cardFieldEl.innerHTML = '';
      if (cards.length === 0) {
        showError('Auf diesem Board gibt es keine Karte für einen Testlauf.');
        return;
      }
      const select = document.createElement('select');
      cards.forEach((card) => {
        const option = document.createElement('option');
        option.value = String(card.id);
        option.textContent = card.title;
        select.appendChild(option);
      });
      select.addEventListener('change', () => {
        cardIdEl.value = select.value;
      });
      cardIdEl.value = select.value;
      cardFieldEl.appendChild(select);
    } catch (e) {
      showError(e.message);
    }
  })();

  document.getElementById('test-run-form').addEventListener('submit', (event) => {
    hideError();
    if (!/^\d+$/.test(cardIdEl.value.trim())) {
      event.preventDefault();
      showError('Bitte eine Karte auswählen.');
      return;
    }
    if (!confirm('Den Workflow jetzt wirklich gegen die gewählte Karte ausführen?')) {
      event.preventDefault();
    }
  });
})();
