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

  const instanceEl = document.getElementById('instance');
  // Hidden inputs hold the actual value (a board/stack id); the visible
  // typeahead widgets are mounted into -field next to them and only ever
  // write into these, same split as getValue/setValue below for the
  // user/calendar search fields.
  const boardEl = document.getElementById('board');
  const stackEl = document.getElementById('stack');
  const boardFieldEl = document.getElementById('board-field');
  const stackFieldEl = document.getElementById('stack-field');

  function mountBoardField(boards) {
    boardEl.value = '';
    boardFieldEl.innerHTML = '';
    boardFieldEl.appendChild(
      renderTypeahead({
        value: '',
        placeholder: 'Board-Name eingeben',
        setValue: (value) => {
          boardEl.value = value;
        },
        loadOptions: (query) => filterByTitle(boards, query),
        onPick: async (item) => {
          hideError();
          mountStackField([], '– lädt –');
          try {
            const data = await fetchJSON(
              'api_stacks.php?instance=' + encodeURIComponent(instanceEl.value) + '&board_id=' + encodeURIComponent(item.id)
            );
            mountStackField(data.stacks);
          } catch (e) {
            showError(e.message);
          }
        },
      })
    );
  }

  function mountStackField(stacks, placeholder) {
    stackEl.value = '';
    stackFieldEl.innerHTML = '';
    if (placeholder) {
      stackFieldEl.appendChild(document.createTextNode(placeholder));
      stackFieldEl.className = 'muted';
      return;
    }
    stackFieldEl.className = '';
    const allColumns = { id: '', title: 'Alle Spalten' };
    stackFieldEl.appendChild(
      renderTypeahead({
        value: '',
        placeholder: 'Spaltenname eingeben (leer = alle Spalten)',
        setValue: (value) => {
          stackEl.value = value;
        },
        loadOptions: (query) => filterByTitle([allColumns, ...stacks], query),
      })
    );
  }

  // Shared substring match (case-insensitive) for the already-fetched,
  // small lists (boards/stacks/calendars) - unlike user search, these don't
  // need a server round-trip per keystroke.
  function filterByTitle(items, query) {
    const q = query.trim().toLowerCase();
    return items
      .filter((item) => item.title.toLowerCase().includes(q))
      .map((item) => ({ id: String(item.id), label: item.title }));
  }

  instanceEl.addEventListener('change', async () => {
    hideError();
    calendarsCache = null; // a different instance has different calendars
    mountStackField([], '– zuerst Board wählen –');
    boardFieldEl.innerHTML = '';
    boardFieldEl.className = 'muted';
    boardFieldEl.textContent = '– lädt –';
    boardEl.value = '';
    if (!instanceEl.value) {
      boardFieldEl.textContent = '– zuerst Instanz wählen –';
      return;
    }
    try {
      const data = await fetchJSON('api_boards.php?instance=' + encodeURIComponent(instanceEl.value));
      mountBoardField(data.boards);
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

  // Generic "type a name, pick from a dropdown" field - every place that
  // references real Nextcloud data by id (a user, a board, a stack, a
  // calendar) uses this same widget instead of asking someone to know and
  // type the underlying id directly.
  //
  // config:
  //   value        - initial text
  //   setValue(v)  - called on every keystroke *and* on picking a result,
  //                  so pasting a known id works even if nothing is ever
  //                  picked from the dropdown
  //   placeholder
  //   loadOptions(query) -> [{id, label}] | Promise<[{id, label}]>
  //   minChars     - don't call loadOptions below this length (default 0)
  //   debounceMs   - delay before calling loadOptions (default 0 - used
  //                  for the already-fetched, small lists; user search sets
  //                  this since it hits the network per keystroke)
  //   onPick(item) - optional, called only when a result is actually
  //                  clicked (e.g. to cascade-load a board's stacks)
  function renderTypeahead(config) {
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

  // assign_user/unassign_user's user_id and calendar_lookup's calendar_id
  // are the module param fields that benefit from search-by-name instead of
  // typing a raw id/CalDAV path - handled as hardcoded special cases rather
  // than a general field-type system that nothing else currently needs.
  function isUserIdField(moduleName, key) {
    return (moduleName === 'assign_user' || moduleName === 'unassign_user') && key === 'user_id';
  }

  function isCalendarIdField(moduleName, key) {
    return moduleName === 'calendar_lookup' && key === 'calendar_id';
  }

  function renderUserSearchField(getValue, setValue) {
    return renderTypeahead({
      value: getValue() || '',
      setValue,
      placeholder: 'Name eingeben (ab 3 Zeichen) oder User-Id direkt eintragen',
      minChars: 3,
      debounceMs: 300,
      loadOptions: async (query) => {
        if (!instanceEl.value) {
          return [];
        }
        const data = await fetchJSON(
          'api_users.php?instance=' + encodeURIComponent(instanceEl.value) + '&query=' + encodeURIComponent(query)
        );
        return (data.users || []).map((user) => ({ id: user.id, label: user.label }));
      },
    });
  }

  // Calendars are a short, per-instance list (like boards/stacks) - fetched
  // once and cached here, then filtered client-side as the user types,
  // instead of a server round-trip per keystroke like the user search above.
  let calendarsCache = null;

  function renderCalendarSearchField(getValue, setValue) {
    return renderTypeahead({
      value: getValue() || '',
      setValue,
      placeholder: 'Kalendername eingeben oder CalDAV-Pfad direkt eintragen',
      loadOptions: async (query) => {
        if (!instanceEl.value) {
          return [];
        }
        if (!calendarsCache) {
          const data = await fetchJSON('api_calendars.php?instance=' + encodeURIComponent(instanceEl.value));
          calendarsCache = data.calendars || [];
        }
        return filterByTitle(calendarsCache, query);
      },
    });
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
    } else if (opts.isCalendarId) {
      wrapper.appendChild(
        renderCalendarSearchField(
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
        isCalendarId: isCalendarIdField(step.module, key),
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

  // A board/stack id only ever becomes valid by picking a suggestion from
  // the typeahead (see renderTypeahead's onPick/setValue) - typing text
  // that was never picked leaves it as non-numeric, which this catches
  // with a clear message instead of silently sending NaN to save.php.
  function parseId(value, label) {
    if (value.trim() === '') {
      return null;
    }
    if (!/^\d+$/.test(value.trim())) {
      throw new Error(label + " '" + value + "' ist kein gültiges Board/Spalte - bitte aus der Liste auswählen.");
    }
    return Number(value);
  }

  function collectPayload() {
    if (!instanceEl.value) {
      throw new Error('Bitte Instanz auswählen.');
    }
    const boardId = parseId(boardEl.value, 'Board');
    if (boardId === null) {
      throw new Error('Bitte ein Board aus der Liste auswählen.');
    }
    const stackId = parseId(stackEl.value, 'Spalte');
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
      board_id: boardId,
      stack_id: stackId,
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
