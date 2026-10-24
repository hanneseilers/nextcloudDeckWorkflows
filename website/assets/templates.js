// "Vorlagen" page: remembers whether the help box was closed, lists the
// placeholders of the text being edited, warns before leaving with unsaved
// changes and asks before deleting.
(function () {
  'use strict';

  // -- help box: open the first time, then as the person left it ---------------------
  const help = document.getElementById('template-help');
  if (help) {
    try {
      if (localStorage.getItem('ncdw.templateHelp') === 'closed') {
        help.open = false;
      }
    } catch (e) { /* storage blocked: stays open */ }
    help.addEventListener('toggle', () => {
      try {
        localStorage.setItem('ncdw.templateHelp', help.open ? 'open' : 'closed');
      } catch (e) { /* ignore */ }
    });
  }

  // -- placeholders ---------------------------------------------------------------------
  const subject = document.getElementById('template-subject');
  const body = document.getElementById('template-body');
  const list = document.getElementById('template-placeholders');

  // What string.Template substitutes: $name, ${name}; "$$" is a literal dollar sign.
  function placeholders(text) {
    const found = [];
    const pattern = /\$(?:\$|([_a-zA-Z][_a-zA-Z0-9]*)|\{([_a-zA-Z][_a-zA-Z0-9]*)\})/g;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      const name = match[2] || match[1];
      if (name && !found.includes(name)) {
        found.push(name);
      }
    }
    return found;
  }

  function showPlaceholders() {
    if (!list || !body) {
      return;
    }
    const names = placeholders((subject ? subject.value + '\n' : '') + body.value);
    list.textContent = '';
    if (names.length === 0) {
      list.textContent = list.dataset.empty || '';
      list.className = 'small muted';
      return;
    }
    list.className = 'small';
    list.append('Platzhalter in dieser Vorlage: ');
    names.forEach((name, index) => {
      if (index > 0) {
        list.append(', ');
      }
      const code = document.createElement('code');
      code.textContent = '$' + name;
      list.appendChild(code);
    });
    list.append(' - jeder braucht beim Verwenden einen Wert (Variable oder Eintrag unter „Werte“).');
  }

  // -- unsaved changes ------------------------------------------------------------------------
  const form = document.getElementById('template-form');
  let dirty = false;
  let submitting = false;
  if (form) {
    form.addEventListener('input', () => {
      dirty = true;
      showPlaceholders();
    });
    form.addEventListener('submit', () => {
      submitting = true;
    });
    window.addEventListener('beforeunload', (event) => {
      if (dirty && !submitting) {
        event.preventDefault();
        event.returnValue = '';
      }
    });
  }
  showPlaceholders();

  // -- delete: ask first ------------------------------------------------------------------------
  document.querySelectorAll('form[data-confirm]').forEach((deleteForm) => {
    deleteForm.addEventListener('submit', (event) => {
      if (!window.confirm(deleteForm.dataset.confirm)) {
        event.preventDefault();
      } else {
        submitting = true;
      }
    });
  });
})();
