/**
 * Drives the "new workflow" form: board/stack pickers (AJAX), and the module
 * chain builder where each step's params are either a literal value or a
 * {"$ref": "<step_id>.<field>"} mapping - the same convention
 * automation/core/domain/engine.py resolves at run time.
 *
 * The chain is a tree, not a flat list: a step is either
 *   {kind: 'action', id, module, params}
 * or a branching step
 *   {kind: 'if', condition: {left, op, right}, then: [...nodes], else: [...nodes]}
 * (`left`/`right` are the same {source, value, refStep, refField} shape as a
 * param entry). `state.steps` is the top-level list; `then`/`else` are nested
 * lists of the same shape, so the whole tree renders/collects recursively.
 *
 * $ref sources offered in the UI are gathered from the *whole* tree
 * (collectAllSteps), not just "earlier in this branch" - simpler than
 * tracking per-branch execution order, and harmless even if a suggested step
 * wouldn't actually have run yet: the engine resolves a bad/premature $ref to
 * `None` and logs a warning rather than crashing (see
 * automation.core.domain.engine._resolve_ref).
 *
 * Everything under #steps is fully re-rendered from `state` on every change -
 * the DOM is never patched in place, mirroring the rest of this file's
 * existing style.
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

  const CONDITION_OPS = [
    ['eq', '='],
    ['ne', '≠'],
    ['lt', '<'],
    ['gt', '>'],
    ['contains', 'enthält'],
    ['beginswith', 'beginnt mit'],
    ['endswith', 'endet mit'],
  ];

  const state = { steps: [] };
  let idManuallyEdited = false;
  let stepCounter = 1; // unique default step ids regardless of nesting/removal

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
    stackEl.innerHTML = '';
    const anyOpt = document.createElement('option');
    anyOpt.value = '';
    anyOpt.textContent = 'Alle Spalten';
    stackEl.appendChild(anyOpt);
    stackEl.disabled = true;
    if (!boardEl.value) {
      return;
    }
    try {
      const data = await fetchJSON(
        'api_stacks.php?instance=' + encodeURIComponent(instanceEl.value) + '&board_id=' + encodeURIComponent(boardEl.value)
      );
      data.stacks.forEach((item) => {
        const option = document.createElement('option');
        option.value = String(item.id);
        option.textContent = item.title + ' (#' + item.id + ')';
        stackEl.appendChild(option);
      });
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

  // -- step tree: data helpers -----------------------------------------------

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

  function makeActionNode() {
    const firstModule = moduleNames[0] || '';
    return {
      kind: 'action',
      id: 'step' + stepCounter++,
      module: firstModule,
      params: defaultParamsFor(firstModule),
    };
  }

  function makeIfNode() {
    return {
      kind: 'if',
      condition: {
        left: { source: 'literal', value: '' },
        op: 'eq',
        right: { source: 'literal', value: '' },
      },
      then: [],
      else: [],
    };
  }

  function collectAllSteps(list) {
    let result = [];
    list.forEach((node) => {
      if (node.kind === 'action') {
        result.push(node);
      } else {
        result = result.concat(collectAllSteps(node.then), collectAllSteps(node.else));
      }
    });
    return result;
  }

  function collectVariableNames(list) {
    return collectAllSteps(list)
      .filter((node) => node.module === 'set_variable' && node.params.name && node.params.name.source === 'literal')
      .map((node) => node.params.name.value)
      .filter((name) => !!name);
  }

  // -- rendering: shared value/operand widgets --------------------------------

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

  // assign_user/unassign_user's user_id is the one field across all shipped
  // modules that benefits from search-by-name instead of typing a raw id -
  // handled as a single special case rather than a general field-type system
  // that nothing else currently needs.
  function isUserIdField(moduleName, key) {
    return (moduleName === 'assign_user' || moduleName === 'unassign_user') && key === 'user_id';
  }

  function renderUserSearchField(getValue, setValue) {
    const wrapper = document.createElement('div');
    wrapper.className = 'user-search';

    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Name eingeben (ab 3 Zeichen) oder User-Id direkt eintragen';
    input.value = getValue() || '';

    const resultsEl = document.createElement('div');
    resultsEl.className = 'user-search-results';
    resultsEl.hidden = true;

    let debounceTimer = null;

    function showResults(users) {
      resultsEl.innerHTML = '';
      if (users.length === 0) {
        resultsEl.hidden = true;
        return;
      }
      users.forEach((user) => {
        const item = document.createElement('div');
        item.className = 'user-search-result';
        item.textContent = user.label + ' (' + user.id + ')';
        item.addEventListener('click', () => {
          setValue(user.id);
          input.value = user.id;
          resultsEl.hidden = true;
        });
        resultsEl.appendChild(item);
      });
      resultsEl.hidden = false;
    }

    input.addEventListener('input', () => {
      // Typing directly always sets the literal value too, so pasting a
      // known user id works without ever touching the search results.
      setValue(input.value);
      resultsEl.hidden = true;

      if (debounceTimer) {
        clearTimeout(debounceTimer);
      }
      const query = input.value.trim();
      if (query.length < 3 || !instanceEl.value) {
        return;
      }
      debounceTimer = setTimeout(async () => {
        try {
          const data = await fetchJSON(
            'api_users.php?instance=' + encodeURIComponent(instanceEl.value) + '&query=' + encodeURIComponent(query)
          );
          showResults(data.users || []);
        } catch (e) {
          // Non-fatal: the field still works as a plain text input even if
          // the search itself fails (unreachable instance, etc.).
        }
      }, 300);
    });

    wrapper.appendChild(input);
    wrapper.appendChild(resultsEl);
    return wrapper;
  }

  // Renders the literal-vs-ref editor for any {source, value, refStep,
  // refField} entry - used for both a module's params (where the literal
  // side's input type comes from the module's declared default value) and an
  // if-condition's operands (always a plain text literal, no module/type to
  // derive from).
  function renderValueOrRefEditor(entry, options) {
    const opts = options || {};
    const wrapper = document.createElement('span');
    wrapper.className = 'value-or-ref';

    const sourceSelect = document.createElement('select');
    ['literal', 'ref'].forEach((source) => {
      const option = document.createElement('option');
      option.value = source;
      option.textContent = source === 'literal' ? 'Fester Wert' : 'Referenz';
      option.selected = entry.source === source;
      sourceSelect.appendChild(option);
    });
    sourceSelect.addEventListener('change', () => {
      entry.source = sourceSelect.value;
      render();
    });
    wrapper.appendChild(sourceSelect);

    if (entry.source === 'ref') {
      const refSources = [{ id: 'card' }, { id: 'vars' }, ...collectAllSteps(state.steps)];
      const refSelect = document.createElement('select');
      const emptyOpt = document.createElement('option');
      emptyOpt.value = '';
      emptyOpt.textContent = '– Quelle wählen –';
      refSelect.appendChild(emptyOpt);
      refSources.forEach((source) => {
        const option = document.createElement('option');
        option.value = source.id;
        option.textContent = source.module ? source.id + ' (' + source.module + ')' : source.id;
        option.selected = source.id === entry.refStep;
        refSelect.appendChild(option);
      });
      refSelect.addEventListener('change', () => {
        entry.refStep = refSelect.value;
      });
      wrapper.appendChild(refSelect);

      const listId = 'ref-fields-' + Math.random().toString(36).slice(2);
      const fieldInput = document.createElement('input');
      fieldInput.type = 'text';
      fieldInput.placeholder = 'Ausgabefeld, z.B. summary';
      fieldInput.value = entry.refField || '';
      fieldInput.setAttribute('list', listId);
      fieldInput.addEventListener('input', () => {
        entry.refField = fieldInput.value;
      });
      wrapper.appendChild(fieldInput);

      const datalist = document.createElement('datalist');
      datalist.id = listId;
      let fieldOptions;
      if (entry.refStep === 'card') {
        fieldOptions = CARD_FIELDS;
      } else if (entry.refStep === 'vars') {
        fieldOptions = collectVariableNames(state.steps);
      } else {
        const refStepObj = refSources.find((s) => s.id === entry.refStep);
        const refModule = refStepObj ? modulesByName[refStepObj.module] : null;
        fieldOptions = Object.keys((refModule && refModule.output) || {});
      }
      fieldOptions.forEach((field) => {
        const option = document.createElement('option');
        option.value = field;
        datalist.appendChild(option);
      });
      wrapper.appendChild(datalist);
    } else if (opts.isUserId) {
      wrapper.appendChild(
        renderUserSearchField(
          () => entry.value,
          (value) => {
            entry.value = value;
          }
        )
      );
    } else {
      const input = renderValueInput(opts.defaultValue !== undefined ? opts.defaultValue : '', entry.value);
      const isCheckbox = input.type === 'checkbox';
      const isTextarea = input.tagName === 'TEXTAREA';
      input.addEventListener('input', () => {
        if (isCheckbox) {
          entry.value = input.checked;
        } else if (isTextarea) {
          // Object/array field: keep the textarea's raw JSON text parsed into a
          // real value. On invalid JSON, flag it and keep the last good value -
          // collectPayload() refuses to submit while any field is flagged.
          try {
            entry.value = input.value.trim() === '' ? opts.defaultValue : JSON.parse(input.value);
            input.classList.remove('invalid');
          } catch (e) {
            input.classList.add('invalid');
          }
        } else if (input.type === 'number') {
          entry.value = input.value === '' ? opts.defaultValue : Number(input.value);
        } else if (input.dataset.valueType === 'nullable-string' && input.value === '') {
          entry.value = null;
        } else {
          entry.value = input.value;
        }
      });
      wrapper.appendChild(input);
    }

    return wrapper;
  }

  // -- rendering: step tree ----------------------------------------------------

  function renderParamRow(step, key, defaultValue) {
    const row = document.createElement('div');
    row.className = 'param-row';

    const label = document.createElement('label');
    label.textContent = key;
    row.appendChild(label);

    row.appendChild(
      renderValueOrRefEditor(step.params[key], {
        defaultValue,
        isUserId: isUserIdField(step.module, key),
      })
    );

    return row;
  }

  function renderActionNode(step, list, index) {
    const wrapper = document.createElement('div');
    wrapper.className = 'step';

    const header = document.createElement('div');
    header.className = 'step-header';

    const idInput = document.createElement('input');
    idInput.type = 'text';
    idInput.value = step.id;
    idInput.title = 'Schritt-Id (für $ref aus anderen Schritten)';
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

    header.appendChild(renderMoveRemoveControls(list, index));
    wrapper.appendChild(header);

    const module = modulesByName[step.module];
    const paramsEl = document.createElement('div');
    paramsEl.className = 'params';

    if (module) {
      const keys = Object.keys(module.input || {});
      keys.forEach((key) => {
        paramsEl.appendChild(renderParamRow(step, key, module.input[key]));
      });
      if (keys.length === 0) {
        const none = document.createElement('p');
        none.className = 'muted';
        none.textContent = 'Dieses Modul benötigt keine Parameter.';
        paramsEl.appendChild(none);
      }
    }
    wrapper.appendChild(paramsEl);

    return wrapper;
  }

  function renderMoveRemoveControls(list, index) {
    const controls = document.createElement('span');

    const upBtn = document.createElement('button');
    upBtn.type = 'button';
    upBtn.textContent = '↑';
    upBtn.addEventListener('click', () => moveNode(list, index, -1));
    controls.appendChild(upBtn);

    const downBtn = document.createElement('button');
    downBtn.type = 'button';
    downBtn.textContent = '↓';
    downBtn.addEventListener('click', () => moveNode(list, index, 1));
    controls.appendChild(downBtn);

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.textContent = 'Entfernen';
    removeBtn.addEventListener('click', () => removeNode(list, index));
    controls.appendChild(removeBtn);

    return controls;
  }

  function renderIfNode(node, list, index) {
    const wrapper = document.createElement('div');
    wrapper.className = 'step if-step';

    const header = document.createElement('div');
    header.className = 'step-header';

    const label = document.createElement('strong');
    label.textContent = 'Wenn';
    header.appendChild(label);

    header.appendChild(renderValueOrRefEditor(node.condition.left, {}));

    const opSelect = document.createElement('select');
    CONDITION_OPS.forEach(([value, text]) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = text;
      option.selected = node.condition.op === value;
      opSelect.appendChild(option);
    });
    opSelect.addEventListener('change', () => {
      node.condition.op = opSelect.value;
    });
    header.appendChild(opSelect);

    header.appendChild(renderValueOrRefEditor(node.condition.right, {}));
    header.appendChild(renderMoveRemoveControls(list, index));
    wrapper.appendChild(header);

    wrapper.appendChild(renderBranch('Dann:', node.then));
    wrapper.appendChild(renderBranch('Sonst:', node.else));

    return wrapper;
  }

  function renderBranch(labelText, branchSteps) {
    const section = document.createElement('div');
    section.className = 'branch';

    const label = document.createElement('div');
    label.className = 'branch-label';
    label.textContent = labelText;
    section.appendChild(label);

    const container = document.createElement('div');
    container.className = 'branch-steps';
    section.appendChild(container);
    renderStepList(branchSteps, container);

    return section;
  }

  function renderStepList(list, container) {
    list.forEach((node, index) => {
      container.appendChild(node.kind === 'if' ? renderIfNode(node, list, index) : renderActionNode(node, list, index));
    });

    const controls = document.createElement('div');
    controls.className = 'step-list-controls';

    const addStepBtn = document.createElement('button');
    addStepBtn.type = 'button';
    addStepBtn.textContent = '+ Schritt';
    addStepBtn.addEventListener('click', () => {
      list.push(makeActionNode());
      render();
    });
    controls.appendChild(addStepBtn);

    const addIfBtn = document.createElement('button');
    addIfBtn.type = 'button';
    addIfBtn.textContent = '+ Wenn/Sonst';
    addIfBtn.addEventListener('click', () => {
      list.push(makeIfNode());
      render();
    });
    controls.appendChild(addIfBtn);

    container.appendChild(controls);
  }

  function removeNode(list, index) {
    list.splice(index, 1);
    render();
  }

  function moveNode(list, index, direction) {
    const target = index + direction;
    if (target < 0 || target >= list.length) {
      return;
    }
    const [node] = list.splice(index, 1);
    list.splice(target, 0, node);
    render();
  }

  function render() {
    stepsEl.innerHTML = '';
    renderStepList(state.steps, stepsEl);
  }

  // -- assembling the payload for save.php ----------------------------------

  function operandValue(entry) {
    if (entry.source === 'ref') {
      if (!entry.refStep || !entry.refField) {
        throw new Error('Eine Referenz ist noch nicht vollständig ausgefüllt (Quelle/Feld fehlt).');
      }
      return { $ref: entry.refStep + '.' + entry.refField };
    }
    return entry.value === undefined ? null : entry.value;
  }

  function collectSteps(list, seenIds) {
    return list.map((node) => {
      if (node.kind === 'if') {
        return {
          type: 'if',
          condition: {
            left: operandValue(node.condition.left),
            op: node.condition.op,
            right: operandValue(node.condition.right),
          },
          then: collectSteps(node.then, seenIds),
          else: collectSteps(node.else, seenIds),
        };
      }

      const id = node.id.trim();
      if (!id) {
        throw new Error('Jeder Schritt braucht eine Id.');
      }
      if (seenIds.has(id)) {
        throw new Error("Schritt-Id '" + id + "' wird mehrfach verwendet.");
      }
      seenIds.add(id);

      const params = {};
      Object.keys(node.params).forEach((key) => {
        params[key] = operandValue(node.params[key]);
      });

      return { id, module: node.module, params };
    });
  }

  function collectPayload() {
    if (!instanceEl.value || !boardEl.value) {
      throw new Error('Bitte Instanz und Board auswählen.');
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

    return {
      instance: instanceEl.value,
      board_id: Number(boardEl.value),
      stack_id: stackEl.value === '' ? null : Number(stackEl.value),
      event: document.getElementById('event-type').value,
      name: nameEl.value.trim(),
      id: idEl.value.trim(),
      steps: collectSteps(state.steps, new Set()),
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

  state.steps.push(makeActionNode());
  render();
})();
