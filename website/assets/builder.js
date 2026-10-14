/**
 * Drives the "new workflow" form: board/stack pickers (AJAX), and the module
 * chain builder where each step's params are either a literal value or a
 * {"$ref": "<step_id>.<field>"} mapping from an earlier step's output - the
 * same convention automation/core/domain/engine.py resolves at run time.
 *
 * All state lives in `state.steps`; the DOM under #steps is fully re-rendered
 * from it on every change, so the DOM never has to be patched in place.
 */
(function () {
  'use strict';

  const modulesByName = {};
  JSON.parse(document.getElementById('modules-data').textContent).forEach((m) => {
    modulesByName[m.name] = m;
  });
  const moduleNames = Object.keys(modulesByName).sort();

  // "card" is a reserved $ref source (see automation/README.md): the raw
  // Nextcloud Deck fields of the card that triggered the workflow, always
  // available without adding a step. This list is only used to populate the
  // field-name datalist below - the actual value comes straight from the
  // Deck API at run time, so any other field name the API returns also works.
  const CARD_FIELDS = [
    'title', 'description', 'duedate', 'labels', 'assignedUsers', 'owner', 'done', 'archived',
  ];

  const state = { steps: [] };
  let idManuallyEdited = false;

  const stepsEl = document.getElementById('steps');
  const errorEl = document.getElementById('error-banner');

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
  }

  function hideError() {
    errorEl.hidden = true;
  }

  function slugify(text) {
    return text
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  // -- instance -> board -> stack pickers --------------------------------

  async function fetchJSON(url) {
    const response = await fetch(url);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `Request to ${url} failed`);
    }
    return data;
  }

  function fillSelect(select, items, placeholder) {
    select.innerHTML = '';
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = placeholder;
    select.appendChild(empty);
    items.forEach((item) => {
      const option = document.createElement('option');
      option.value = String(item.id);
      option.textContent = item.title + ' (#' + item.id + ')';
      select.appendChild(option);
    });
  }

  const instanceEl = document.getElementById('instance');
  const boardEl = document.getElementById('board');
  const stackEl = document.getElementById('stack');

  instanceEl.addEventListener('change', async () => {
    hideError();
    fillSelect(boardEl, [], '– lädt –');
    fillSelect(stackEl, [], '– zuerst Board wählen –');
    boardEl.disabled = true;
    stackEl.disabled = true;
    if (!instanceEl.value) {
      return;
    }
    try {
      const data = await fetchJSON('api_boards.php?instance=' + encodeURIComponent(instanceEl.value));
      fillSelect(boardEl, data.boards, '– wählen –');
      boardEl.disabled = false;
    } catch (e) {
      showError(e.message);
    }
  });

  boardEl.addEventListener('change', async () => {
    hideError();
    fillSelect(stackEl, [], '– lädt –');
    stackEl.disabled = true;
    if (!boardEl.value) {
      return;
    }
    try {
      const data = await fetchJSON(
        'api_stacks.php?instance=' + encodeURIComponent(instanceEl.value) + '&board_id=' + encodeURIComponent(boardEl.value)
      );
      fillSelect(stackEl, data.stacks, '– wählen –');
      stackEl.disabled = false;
    } catch (e) {
      showError(e.message);
    }
  });

  // -- workflow id suggestion from name -----------------------------------

  const nameEl = document.getElementById('name');
  const idEl = document.getElementById('workflow-id');
  nameEl.addEventListener('input', () => {
    if (!idManuallyEdited) {
      idEl.value = slugify(nameEl.value);
    }
  });
  idEl.addEventListener('input', () => {
    idManuallyEdited = true;
  });

  // -- step/module chain builder -------------------------------------------

  function defaultParamsFor(moduleName) {
    const module = modulesByName[moduleName];
    const params = {};
    if (!module) {
      return params;
    }
    Object.keys(module.input || {}).forEach((key) => {
      params[key] = { source: 'literal', value: module.input[key] };
    });
    return params;
  }

  function addStep() {
    const firstModule = moduleNames[0] || '';
    state.steps.push({
      id: 'step' + (state.steps.length + 1),
      module: firstModule,
      params: defaultParamsFor(firstModule),
    });
    render();
  }

  function removeStep(index) {
    state.steps.splice(index, 1);
    render();
  }

  function moveStep(index, direction) {
    const target = index + direction;
    if (target < 0 || target >= state.steps.length) {
      return;
    }
    const [step] = state.steps.splice(index, 1);
    state.steps.splice(target, 0, step);
    render();
  }

  function renderValueInput(defaultValue, currentValue) {
    const type = defaultValue === null ? 'nullable-string' : typeof defaultValue;
    let input;
    if (type === 'boolean') {
      input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = currentValue === undefined ? !!defaultValue : !!currentValue;
    } else if (type === 'number') {
      input = document.createElement('input');
      input.type = 'number';
      input.step = 'any';
      input.value = currentValue === undefined ? defaultValue : currentValue;
    } else if (type === 'object') {
      input = document.createElement('textarea');
      input.placeholder = JSON.stringify(defaultValue);
      input.value = currentValue === undefined ? '' : JSON.stringify(currentValue, null, 2);
      input.dataset.jsonField = 'true';
    } else {
      input = document.createElement('input');
      input.type = 'text';
      input.placeholder = type === 'nullable-string' ? '(optional)' : String(defaultValue);
      input.value = currentValue === undefined || currentValue === null ? '' : currentValue;
    }
    input.dataset.valueType = type;
    return input;
  }

  function renderStep(step, index) {
    const wrapper = document.createElement('div');
    wrapper.className = 'step';

    const header = document.createElement('div');
    header.className = 'step-header';

    const idInput = document.createElement('input');
    idInput.type = 'text';
    idInput.value = step.id;
    idInput.title = 'Schritt-Id (für $ref aus späteren Schritten)';
    idInput.addEventListener('input', () => {
      step.id = idInput.value;
    });
    header.appendChild(idInput);

    const moduleSelect = document.createElement('select');
    moduleNames.forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      option.selected = name === step.module;
      moduleSelect.appendChild(option);
    });
    moduleSelect.addEventListener('change', () => {
      step.module = moduleSelect.value;
      step.params = defaultParamsFor(step.module);
      render();
    });
    header.appendChild(moduleSelect);

    const upBtn = document.createElement('button');
    upBtn.type = 'button';
    upBtn.textContent = '↑';
    upBtn.addEventListener('click', () => moveStep(index, -1));
    header.appendChild(upBtn);

    const downBtn = document.createElement('button');
    downBtn.type = 'button';
    downBtn.textContent = '↓';
    downBtn.addEventListener('click', () => moveStep(index, 1));
    header.appendChild(downBtn);

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.textContent = 'Entfernen';
    removeBtn.addEventListener('click', () => removeStep(index));
    header.appendChild(removeBtn);

    wrapper.appendChild(header);

    const module = modulesByName[step.module];
    const paramsEl = document.createElement('div');
    paramsEl.className = 'params';

    if (module) {
      Object.keys(module.input || {}).forEach((key) => {
        paramsEl.appendChild(renderParamRow(step, index, key, module.input[key]));
      });
      if (Object.keys(module.input || {}).length === 0) {
        const none = document.createElement('p');
        none.className = 'muted';
        none.textContent = 'Dieses Modul benötigt keine Parameter.';
        paramsEl.appendChild(none);
      }
    }
    wrapper.appendChild(paramsEl);

    return wrapper;
  }

  function renderParamRow(step, index, key, defaultValue) {
    const row = document.createElement('div');
    row.className = 'param-row';

    const label = document.createElement('label');
    label.textContent = key;
    row.appendChild(label);

    const sourceSelect = document.createElement('select');
    ['literal', 'ref'].forEach((source) => {
      const option = document.createElement('option');
      option.value = source;
      option.textContent = source === 'literal' ? 'Fester Wert' : 'Aus vorherigem Schritt';
      option.selected = step.params[key].source === source;
      sourceSelect.appendChild(option);
    });
    sourceSelect.addEventListener('change', () => {
      step.params[key].source = sourceSelect.value;
      if (sourceSelect.value === 'ref' && !step.params[key].refStep) {
        step.params[key].refStep = '';
        step.params[key].refField = '';
      }
      render();
    });
    row.appendChild(sourceSelect);

    if (step.params[key].source === 'ref') {
      // "card" (the triggering card's raw fields) is always selectable, in
      // addition to any earlier step in this workflow.
      const refSources = [{ id: 'card', module: null }, ...state.steps.slice(0, index)];
      const refSelect = document.createElement('select');
      const emptyOpt = document.createElement('option');
      emptyOpt.value = '';
      emptyOpt.textContent = '– Quelle wählen –';
      refSelect.appendChild(emptyOpt);
      refSources.forEach((source) => {
        const option = document.createElement('option');
        option.value = source.id;
        option.textContent = source.module ? source.id + ' (' + source.module + ')' : source.id;
        option.selected = source.id === step.params[key].refStep;
        refSelect.appendChild(option);
      });
      refSelect.addEventListener('change', () => {
        step.params[key].refStep = refSelect.value;
      });
      row.appendChild(refSelect);

      const fieldInput = document.createElement('input');
      fieldInput.type = 'text';
      fieldInput.placeholder = 'Ausgabefeld, z.B. summary';
      fieldInput.value = step.params[key].refField || '';
      fieldInput.setAttribute('list', 'output-fields-' + index + '-' + key);
      fieldInput.addEventListener('input', () => {
        step.params[key].refField = fieldInput.value;
      });
      row.appendChild(fieldInput);

      const datalist = document.createElement('datalist');
      datalist.id = 'output-fields-' + index + '-' + key;
      let fieldOptions;
      if (step.params[key].refStep === 'card') {
        fieldOptions = CARD_FIELDS;
      } else {
        const refStepObj = refSources.find((s) => s.id === step.params[key].refStep);
        const refModule = refStepObj ? modulesByName[refStepObj.module] : null;
        fieldOptions = Object.keys((refModule && refModule.output) || {});
      }
      fieldOptions.forEach((field) => {
        const option = document.createElement('option');
        option.value = field;
        datalist.appendChild(option);
      });
      row.appendChild(datalist);
    } else {
      const input = renderValueInput(defaultValue, step.params[key].value);
      const isCheckbox = input.type === 'checkbox';
      const isTextarea = input.tagName === 'TEXTAREA';
      input.addEventListener('input', () => {
        if (isCheckbox) {
          step.params[key].value = input.checked;
        } else if (isTextarea) {
          // Object/array field: keep the textarea's raw JSON text parsed into a
          // real value. On invalid JSON, flag it and keep the last good value -
          // collectPayload() refuses to submit while any field is flagged.
          try {
            step.params[key].value = input.value.trim() === '' ? defaultValue : JSON.parse(input.value);
            input.classList.remove('invalid');
          } catch (e) {
            input.classList.add('invalid');
          }
        } else if (input.type === 'number') {
          step.params[key].value = input.value === '' ? defaultValue : Number(input.value);
        } else if (input.dataset.valueType === 'nullable-string' && input.value === '') {
          step.params[key].value = null;
        } else {
          step.params[key].value = input.value;
        }
      });
      row.appendChild(input);
    }

    return row;
  }

  function render() {
    stepsEl.innerHTML = '';
    state.steps.forEach((step, index) => {
      stepsEl.appendChild(renderStep(step, index));
    });
  }

  document.getElementById('add-step').addEventListener('click', addStep);

  // -- assembling the payload for save.php ----------------------------------

  function paramValue(entry) {
    if (entry.source === 'ref') {
      if (!entry.refStep || !entry.refField) {
        throw new Error('Ein Mapping-Feld ist noch nicht vollständig ausgefüllt (Schritt/Feld fehlt).');
      }
      return { $ref: entry.refStep + '.' + entry.refField };
    }
    return entry.value === undefined ? null : entry.value;
  }

  function collectPayload() {
    if (!instanceEl.value || !boardEl.value || !stackEl.value) {
      throw new Error('Bitte Instanz, Board und Spalte auswählen.');
    }
    if (!nameEl.value.trim() || !idEl.value.trim()) {
      throw new Error('Bitte Name und Id des Workflows angeben.');
    }
    if (state.steps.length === 0) {
      throw new Error('Bitte mindestens einen Schritt hinzufügen.');
    }
    if (stepsEl.querySelector('textarea.invalid')) {
      throw new Error('Ein JSON-Feld enthält ungültiges JSON - bitte prüfen.');
    }

    const seenIds = new Set();
    const steps = state.steps.map((step) => {
      const id = step.id.trim();
      if (!id) {
        throw new Error('Jeder Schritt braucht eine Id.');
      }
      if (seenIds.has(id)) {
        throw new Error("Schritt-Id '" + id + "' wird mehrfach verwendet.");
      }
      seenIds.add(id);

      const params = {};
      Object.keys(step.params).forEach((key) => {
        params[key] = paramValue(step.params[key]);
      });

      return { id, module: step.module, params };
    });

    return {
      instance: instanceEl.value,
      board_id: Number(boardEl.value),
      stack_id: Number(stackEl.value),
      event: document.getElementById('event-type').value,
      name: nameEl.value.trim(),
      id: idEl.value.trim(),
      steps,
    };
  }

  document.getElementById('workflow-form').addEventListener('submit', (event) => {
    hideError();
    try {
      const payload = collectPayload();
      document.getElementById('payload').value = JSON.stringify(payload);
    } catch (e) {
      event.preventDefault();
      showError(e.message);
    }
  });

  addStep();
})();
