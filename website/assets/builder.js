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
  const moduleLabel = (name) => {
    const m = modulesByName[name];
    return m && m.label && m.label !== name ? m.label : name;
  };
  const moduleNames = Object.keys(modulesByName).sort(
    (a, b) => moduleLabel(a).localeCompare(moduleLabel(b), 'de')
  );

  // "card" is a reserved $ref source (see automation/README.md): the raw
  // Nextcloud Deck fields of the card that triggered the workflow, always
  // available without adding a step. This list only feeds the field picker -
  // the actual value comes straight from the Deck API at run time, so any
  // other field name the API returns also works (via "Anderes Feld...").
  // docs.php lists the same fields - keep both in sync.
  const CARD_FIELDS = [
    ['title', 'Titel'],
    ['description', 'Beschreibung'],
    ['duedate', 'Fälligkeitsdatum'],
    ['labels', 'Labels'],
    ['assignedUsers', 'Zugewiesene Benutzer'],
    ['owner', 'Ersteller'],
    ['done', 'Erledigt (Datum)'],
    ['archived', 'Archiviert'],
    ['id', 'Karten-Id'],
    ['stackId', 'Spalten-Id'],
    ['createdAt', 'Erstellt am (Zeitstempel)'],
    ['lastModified', 'Zuletzt geändert (Zeitstempel)'],
    ['lastEditor', 'Zuletzt bearbeitet von'],
    ['order', 'Position in der Spalte'],
    ['overdue', 'Überfällig-Status'],
    ['commentsCount', 'Anzahl Kommentare'],
    ['attachmentCount', 'Anzahl Anhänge'],
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
  // Unsaved-changes guard: set by any edit once the page has finished
  // loading (see the end of this file), cleared by a successful submit.
  let loaded = false;
  let dirty = false;
  let submitting = false;
  function markDirty() {
    if (loaded) {
      dirty = true;
    }
  }
  window.addEventListener('beforeunload', (event) => {
    if (dirty && !submitting) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  let idManuallyEdited = false;
  let stepCounter = 1; // unique default step ids regardless of nesting/removal

  const stepsEl = document.getElementById('steps');
  const errorEl = document.getElementById('error-banner');

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
    errorEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
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

  // Shows a plain "– loading –"/"– pick X first –" text in place of a
  // mounted typeahead - used both for the initial disabled state and while
  // loadAndMount() below is waiting on a request.
  function showPlaceholder(el, text) {
    el.innerHTML = '';
    el.className = 'muted';
    el.textContent = text;
  }

  // Shared by every instance->board->stack step: show a loading placeholder,
  // fetch, then either mount the real field from the response or show the
  // error banner - the one pattern the instance-change and board-pick
  // handlers below both followed independently before.
  async function loadAndMount(url, targetEl, loadingText, onData) {
    hideError();
    showPlaceholder(targetEl, loadingText);
    try {
      const data = await fetchJSON(url);
      onData(data);
    } catch (e) {
      showError(e.message);
    }
  }

  // `preselectId`, when given (edit mode restoring a saved board/stack),
  // sets the hidden value immediately and looks up its title in the
  // already-fetched list for the typeahead's initial display text - if the
  // board/stack no longer exists (renamed/deleted since), the hidden value
  // is still correct for saving, it just displays the raw id as a fallback.
  function mountBoardField(boards, preselectId) {
    const match = preselectId != null ? boards.find((b) => String(b.id) === String(preselectId)) : null;
    boardEl.value = preselectId != null ? String(preselectId) : '';
    boardFieldEl.className = '';
    boardFieldEl.innerHTML = '';
    boardFieldEl.appendChild(
      renderTypeahead({
        value: match ? match.title : boardEl.value,
        placeholder: 'Board-Name eingeben',
        setValue: (value) => {
          boardEl.value = value;
        },
        loadOptions: (query) => filterByTitle(boards, query),
        onPick: (item) => loadStacksFor(item.id),
      })
    );
  }

  function loadStacksFor(boardId, preselectStackId) {
    stackEl.value = preselectStackId != null ? String(preselectStackId) : '';
    loadAndMount(
      'api_stacks.php?instance=' + encodeURIComponent(instanceEl.value) + '&board_id=' + encodeURIComponent(boardId),
      stackFieldEl,
      '– lädt –',
      (data) => mountStackField(data.stacks, preselectStackId)
    );
  }

  function mountStackField(stacks, preselectId) {
    const allColumns = { id: '', title: 'Alle Spalten' };
    const all = [allColumns, ...stacks];
    const match = preselectId != null ? all.find((s) => String(s.id) === String(preselectId)) : null;
    stackEl.value = preselectId != null ? String(preselectId) : '';
    stackFieldEl.className = '';
    stackFieldEl.innerHTML = '';
    stackFieldEl.appendChild(
      renderTypeahead({
        value: match ? match.title : stackEl.value,
        placeholder: 'Spaltenname eingeben (leer = alle Spalten)',
        setValue: (value) => {
          stackEl.value = value;
        },
        loadOptions: (query) => filterByTitle(all, query),
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

  function loadBoardsFor(preselectBoardId, preselectStackId) {
    if (!instanceEl.value) {
      showPlaceholder(boardFieldEl, '– zuerst Instanz wählen –');
      return;
    }
    loadAndMount(
      'api_boards.php?instance=' + encodeURIComponent(instanceEl.value),
      boardFieldEl,
      '– lädt –',
      (data) => {
        mountBoardField(data.boards, preselectBoardId);
        if (preselectBoardId != null) {
          loadStacksFor(preselectBoardId, preselectStackId);
        }
      }
    );
  }

  instanceEl.addEventListener('change', () => {
    calendarsCache = null; // a different instance has different calendars
    boardEl.value = '';
    stackEl.value = '';
    showPlaceholder(stackFieldEl, '– zuerst Board wählen –');
    loadBoardsFor();
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

  // -- event vs. schedule trigger toggle --------------------------------------

  const triggerKindEl = document.getElementById('trigger-kind');
  const eventTriggerFieldsEl = document.getElementById('event-trigger-fields');
  const scheduleTriggerFieldsEl = document.getElementById('schedule-trigger-fields');
  const stackLabelEl = document.getElementById('stack-label');
  const scheduleTimeEl = document.getElementById('schedule-time');
  const weekdayCheckboxes = Array.from(document.querySelectorAll('.schedule-weekday'));

  function applyTriggerKind() {
    const isSchedule = triggerKindEl.value === 'schedule';
    eventTriggerFieldsEl.hidden = isSchedule;
    scheduleTriggerFieldsEl.hidden = !isSchedule;
    stackLabelEl.hidden = isSchedule; // "Spalte" only makes sense for an event trigger
  }

  triggerKindEl.addEventListener('change', applyTriggerKind);
  applyTriggerKind();

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

  // How a value source reads in the "Wert übernehmen" dropdown.
  function sourceLabel(source) {
    if (source.id === 'card') {
      return 'Karte (die den Workflow ausgelöst hat)';
    }
    if (source.id === 'vars') {
      return 'Variablen';
    }
    return 'Schritt ' + stepNumber(source) + ': ' + moduleLabel(source.module);
  }

  // "2" or "3.1" - the number shown in front of a step (see renderStepList).
  function stepNumber(node) {
    return node.displayNumber || node.id;
  }

  // The action steps that run before `target` (an action or if node): every
  // step earlier in the tree, including both branches of an if/else that
  // precedes it - but not the other branch of the if/else `target` sits in,
  // nor anything after it, since those can't have produced a value yet.
  function stepsBefore(target, list = state.steps) {
    const result = [];
    for (const node of list) {
      if (node === target) {
        return { found: true, steps: result };
      }
      if (node.kind === 'action') {
        result.push(node);
        continue;
      }
      for (const branch of [node.then, node.else]) {
        const inner = stepsBefore(target, branch);
        if (inner.found) {
          return { found: true, steps: result.concat(inner.steps) };
        }
      }
      result.push(...collectAllSteps(node.then), ...collectAllSteps(node.else));
    }
    return { found: false, steps: result };
  }

  function variableNamesFrom(steps) {
    return steps
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

  // renderTypeahead() now lives in assets/typeahead.js (new.php loads it
  // before this file) - shared with test_run.php's card picker.

  // assign_user/unassign_user's user_id and calendar_lookup's calendar_id
  // are the module param fields that benefit from search-by-name instead of
  // typing a raw id/CalDAV path - handled as hardcoded special cases rather
  // than a general field-type system that nothing else currently needs.
  // The tiny setValue closure every {source, value, ...} entry's search
  // field needs (renderUserSearchField/renderCalendarSearchField below).
  function bindEntryValue(entry) {
    return (value) => {
      entry.value = value;
    };
  }

  function isUserIdField(moduleName, key) {
    return (moduleName === 'assign_user' || moduleName === 'unassign_user') && key === 'user_id';
  }

  function isCalendarIdField(moduleName, key) {
    return moduleName === 'calendar_lookup' && key === 'calendar_id';
  }

  function isGermanDateTimeField(moduleName, key) {
    return moduleName === 'set_due_date' && key === 'due_date';
  }

  function formatHintFor(moduleName, key) {
    if (moduleName === 'set_due_date' && key === 'due_date') {
      return 'Format: TT.MM.JJJJ hh:mm';
    }
    return '';
  }


  function isStackIdField(moduleName, key) {
    return (moduleName === 'move_card' || moduleName === 'copy_card') && key === 'target_stack_id';
  }

  function isActionNameField(moduleName, key) {
    return moduleName === 'create_action_link' && key === 'action';
  }

  // The action an one-time link runs: a dropdown of every action (not the
  // link action itself), value = the technical name.
  function renderActionSelectField(entry) {
    const select = document.createElement('select');
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '– Action wählen –';
    select.appendChild(placeholder);
    moduleNames.filter((name) => name !== 'create_action_link').forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = moduleLabel(name);
      option.title = name;
      option.selected = name === entry.value;
      select.appendChild(option);
    });
    select.addEventListener('change', () => {
      entry.value = select.value;
      render(); // the step's info box lists the chosen action's fields
    });
    return select;
  }

  function isBoardIdField(moduleName, key) {
    return moduleName === 'copy_card' && key === 'target_board_id';
  }

  function isLabelIdField(moduleName, key) {
    return moduleName === 'add_label' && key === 'label_id';
  }

  // Labels, stacks and boards: fetched once (cached), filtered client-side as
  // the user types, saved as the numeric id - a typed id still works. A saved
  // id is shown as its name. Labels/stacks belong to a board - by default the
  // workflow's own, or whichever `boardIdOf()` returns (copy_card's target
  // board); `boardScoped: false` is for the per-instance board list itself.
  const boardItemsCache = {};

  async function loadScopedItems(endpoint, listKey, boardId, boardScoped) {
    if (!instanceEl.value || (boardScoped && !/^\d+$/.test(String(boardId)))) {
      return [];
    }
    const query = '?instance=' + encodeURIComponent(instanceEl.value)
      + (boardScoped ? '&board_id=' + encodeURIComponent(boardId) : '');
    const key = endpoint + query;
    if (!boardItemsCache[key]) {
      const data = await fetchJSON(endpoint + query);
      boardItemsCache[key] = data[listKey] || [];
    }
    return boardItemsCache[key];
  }

  function renderBoardItemField(entry, { endpoint, listKey, placeholder, boardScoped = true, boardIdOf = () => boardEl.value }) {
    const load = () => loadScopedItems(endpoint, listKey, boardIdOf(), boardScoped);
    const field = renderTypeahead({
      value: entry.value ? String(entry.value) : '',
      setValue: (value) => {
        const text = String(value).trim();
        entry.value = /^\d+$/.test(text) ? Number(text) : value;
        // Free text that was never picked from the list is not an id.
        const input = field && field.querySelector('input');
        if (input) {
          input.classList.toggle('invalid', text !== '' && !/^\d+$/.test(text));
          input.dataset.errorMessage = 'Bitte einen Eintrag aus der Liste wählen oder eine numerische Id eintragen.';
        }
      },
      placeholder,
      loadOptions: async (query) => filterByTitle(await load(), query),
    });
    addSyntaxErrorDisplay(field.querySelector('input'), field);
    // In edit mode the board is restored asynchronously after the steps
    // render, so retry briefly until it is known.
    if (entry.value) {
      let attempts = 0;
      const resolveTitle = () => {
        if (boardScoped && !/^\d+$/.test(String(boardIdOf()))) {
          if (++attempts < 20) {
            setTimeout(resolveTitle, 250);
          }
          return;
        }
        load().then((items) => {
          const match = items.find((item) => String(item.id) === String(entry.value));
          const input = field.querySelector('input');
          if (match && input.value === String(entry.value)) {
            input.value = match.title;
          }
        }).catch(() => {});
      };
      resolveTitle();
    }
    return field;
  }

  function renderLabelSearchField(entry) {
    return renderBoardItemField(entry, {
      endpoint: 'api_labels.php',
      listKey: 'labels',
      placeholder: 'Label-Name eingeben oder Label-Id direkt eintragen',
    });
  }

  function renderStackSearchField(entry, boardIdOf) {
    return renderBoardItemField(entry, {
      endpoint: 'api_stacks.php',
      listKey: 'stacks',
      placeholder: 'Spaltenname eingeben oder Spalten-Id direkt eintragen',
      boardIdOf,
    });
  }

  function renderBoardSearchField(entry) {
    return renderBoardItemField(entry, {
      endpoint: 'api_boards.php',
      listKey: 'boards',
      placeholder: 'Board-Name eingeben oder Board-Id direkt eintragen',
      boardScoped: false,
    });
  }

  function renderUserSearchField(entry) {
    return renderTypeahead({
      value: entry.value || '',
      setValue: bindEntryValue(entry),
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

  function renderCalendarSearchField(entry) {
    return renderTypeahead({
      value: entry.value || '',
      setValue: bindEntryValue(entry),
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
  // Appends the ref-picker UI (source-step select + output-field picker
  // listing the source's known fields, with a free-text fallback) to `wrapper` for an entry whose
  // source is "ref".
  function appendRefOperandFields(wrapper, entry, owner) {
    // Only steps that run before this one can have produced a value.
    const earlier = owner ? stepsBefore(owner).steps : collectAllSteps(state.steps);
    const refSources = [{ id: 'card' }, { id: 'vars' }, ...earlier];
    // A saved reference to a later (or deleted) step stays visible - marked -
    // instead of silently showing an empty choice.
    if (entry.refStep && !refSources.some((source) => source.id === entry.refStep)) {
      const later = collectAllSteps(state.steps).find((node) => node.id === entry.refStep);
      refSources.push(later
        ? { ...later, warning: ' – kommt erst danach, hat hier noch keinen Wert' }
        : { id: entry.refStep, module: null, warning: ' – unbekannter Schritt' });
    }
    const refSelect = document.createElement('select');
    const emptyOpt = document.createElement('option');
    emptyOpt.value = '';
    emptyOpt.textContent = '– Quelle wählen –';
    refSelect.appendChild(emptyOpt);
    refSources.forEach((source) => {
      const option = document.createElement('option');
      option.value = source.id;
      option.textContent = (source.module || source.id === 'card' || source.id === 'vars' ? sourceLabel(source) : source.id) + (source.warning || '');
      option.title = source.id;
      option.selected = source.id === entry.refStep;
      refSelect.appendChild(option);
    });
    wrapper.appendChild(refSelect);

    const fieldBox = document.createElement('span');
    wrapper.appendChild(fieldBox);

    // [value, label] pairs the picker offers for the currently chosen source.
    const fieldOptionsFor = (stepId) => {
      if (stepId === 'card') {
        return CARD_FIELDS;
      }
      if (stepId === 'vars') {
        return variableNamesFrom(earlier).map((name) => [name, name]);
      }
      const refStepObj = refSources.find((s) => s.id === stepId);
      const refModule = refStepObj ? modulesByName[refStepObj.module] : null;
      const outputLabels = (refModule && refModule.output_labels) || {};
      return Object.keys((refModule && refModule.output) || {}).map((name) => [name, outputLabels[name] || name]);
    };

    const renderFieldPicker = () => {
      fieldBox.textContent = '';
      const options = fieldOptionsFor(entry.refStep);
      const fieldInput = document.createElement('input');
      fieldInput.type = 'text';
      fieldInput.placeholder = 'Feldname';
      fieldInput.value = entry.refField || '';
      fieldInput.addEventListener('input', () => {
        entry.refField = fieldInput.value;
      });

      if (options.length === 0) {
        fieldInput.placeholder = 'Ausgabefeld, z.B. summary';
        fieldBox.appendChild(fieldInput);
        return;
      }

      const CUSTOM = '__custom__';
      const fieldSelect = document.createElement('select');
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = '– Feld wählen –';
      fieldSelect.appendChild(placeholder);
      const known = options.some(([value]) => value === entry.refField);
      options.forEach(([value, label]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label === value ? value : label + ' (' + value + ')';
        option.selected = value === entry.refField;
        fieldSelect.appendChild(option);
      });
      const customOpt = document.createElement('option');
      customOpt.value = CUSTOM;
      customOpt.textContent = 'Anderes Feld …';
      const isCustom = !!entry.refField && !known;
      customOpt.selected = isCustom;
      fieldSelect.appendChild(customOpt);
      if (!entry.refField) {
        placeholder.selected = true;
      }

      fieldInput.hidden = !isCustom;
      fieldSelect.addEventListener('change', () => {
        if (fieldSelect.value === CUSTOM) {
          fieldInput.hidden = false;
          fieldInput.focus();
        } else {
          fieldInput.hidden = true;
          entry.refField = fieldSelect.value;
          fieldInput.value = fieldSelect.value;
        }
      });
      fieldBox.appendChild(fieldSelect);
      fieldBox.appendChild(fieldInput);
    };
    renderFieldPicker();

    refSelect.addEventListener('change', () => {
      entry.refStep = refSelect.value;
      entry.refField = '';
      renderFieldPicker();
    });
  }

  // Appends the literal-value input (type derived from the module's default,
  // or a plain text field for an if-condition operand) to `wrapper`.
  // -- German date/time entry (TT.MM.JJJJ hh:mm, local time) <-> stored ISO 8601 --

  const pad2 = (n) => String(n).padStart(2, '0');

  function germanToIso(text) {
    const m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})$/.exec(text.trim());
    if (!m) {
      return null;
    }
    const [day, month, year, hour, minute] = [m[1], m[2], m[3], m[4], m[5]].map(Number);
    const date = new Date(year, month - 1, day, hour, minute);
    if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day
        || date.getHours() !== hour || date.getMinutes() !== minute) {
      return null; // e.g. 31.02. or 25:00 - Date would silently roll over
    }
    const offset = -date.getTimezoneOffset();
    const sign = offset >= 0 ? '+' : '-';
    return year + '-' + pad2(month) + '-' + pad2(day) + 'T' + pad2(hour) + ':' + pad2(minute) + ':00'
      + sign + pad2(Math.floor(Math.abs(offset) / 60)) + ':' + pad2(Math.abs(offset) % 60);
  }

  function isoToGerman(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T/.test(value)) {
      return value == null ? '' : String(value);
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return pad2(date.getDate()) + '.' + pad2(date.getMonth() + 1) + '.' + date.getFullYear()
      + ' ' + pad2(date.getHours()) + ':' + pad2(date.getMinutes());
  }

  // Shows `input.dataset.errorMessage` in a line below the field when the
  // field is flagged .invalid and loses focus; hides it again as soon as the
  // content is valid. Call after the input's own 'input' listener is attached.
  function addSyntaxErrorDisplay(input, wrapper) {
    const errorEl = document.createElement('span');
    errorEl.className = 'field-error';
    errorEl.hidden = true;
    wrapper.appendChild(errorEl);
    input.addEventListener('blur', () => {
      if (input.classList.contains('invalid')) {
        errorEl.textContent = input.dataset.errorMessage || 'Ungültiger Wert.';
        errorEl.hidden = false;
      }
    });
    input.addEventListener('input', () => {
      if (!input.classList.contains('invalid')) {
        errorEl.hidden = true;
      }
    });
  }

  function appendGermanDateTimeField(wrapper, entry, hint) {
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'TT.MM.JJJJ hh:mm';
    input.value = isoToGerman(entry.value);
    input.addEventListener('input', () => {
      const text = input.value.trim();
      if (text === '') {
        entry.value = null;
        input.classList.remove('invalid');
      } else if (/^\d{4}-\d{2}-\d{2}T/.test(text)) {
        entry.value = text; // raw ISO 8601 still accepted
        input.classList.remove('invalid');
      } else {
        const iso = germanToIso(text);
        if (iso === null) {
          input.classList.add('invalid');
          input.dataset.errorMessage = 'Ungültiges Datum - erwartet wird TT.MM.JJJJ hh:mm, z. B. 15.03.2027 14:30.';
        } else {
          entry.value = iso;
          input.classList.remove('invalid');
        }
      }
    });
    wrapper.appendChild(input);
    if (hint) {
      const hintEl = document.createElement('span');
      hintEl.className = 'muted format-hint';
      hintEl.textContent = hint;
      wrapper.appendChild(hintEl);
    }
    addSyntaxErrorDisplay(input, wrapper);
  }

  function appendLiteralOperandField(wrapper, entry, opts) {
    if (opts.germanDateTime) {
      appendGermanDateTimeField(wrapper, entry, opts.formatHint);
      return;
    }
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
          input.dataset.errorMessage = 'Ungültiges JSON: ' + e.message;
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
    if (opts.formatHint) {
      const hint = document.createElement('span');
      hint.className = 'muted format-hint';
      hint.textContent = opts.formatHint;
      wrapper.appendChild(hint);
    }
    if (isTextarea) {
      addSyntaxErrorDisplay(input, wrapper);
    }
  }

  // Renders the literal-vs-ref editor for any {source, value, refStep,
  // refField} entry (see the module docstring at the top of this file) -
  // just a dispatcher over the three appendX helpers above.
  function renderValueOrRefEditor(entry, options) {
    const opts = options || {};
    const wrapper = document.createElement('span');
    wrapper.className = 'value-or-ref';

    const sourceSelect = document.createElement('select');
    ['literal', 'ref'].forEach((source) => {
      const option = document.createElement('option');
      option.value = source;
      option.textContent = source === 'literal' ? 'Fester Wert' : 'Wert übernehmen';
      option.selected = entry.source === source;
      sourceSelect.appendChild(option);
    });
    sourceSelect.addEventListener('change', () => {
      entry.source = sourceSelect.value;
      render();
    });
    wrapper.appendChild(sourceSelect);

    if (entry.source === 'ref') {
      appendRefOperandFields(wrapper, entry, opts.owner);
    } else if (opts.isUserId) {
      wrapper.appendChild(renderUserSearchField(entry));
    } else if (opts.isActionName) {
      wrapper.appendChild(renderActionSelectField(entry));
    } else if (opts.isBoardId) {
      wrapper.appendChild(renderBoardSearchField(entry));
    } else if (opts.isStackId) {
      wrapper.appendChild(renderStackSearchField(entry, opts.stackBoardIdOf));
    } else if (opts.isLabelId) {
      wrapper.appendChild(renderLabelSearchField(entry));
    } else if (opts.isCalendarId) {
      wrapper.appendChild(renderCalendarSearchField(entry));
    } else {
      appendLiteralOperandField(wrapper, entry, opts);
    }

    return wrapper;
  }

  // -- rendering: step tree ----------------------------------------------------

  function renderParamRow(step, key, defaultValue) {
    const row = document.createElement('div');
    row.className = 'param-row';

    const module = modulesByName[step.module] || {};
    const label = document.createElement('label');
    label.textContent = (module.param_labels || {})[key] || key;
    label.title = key; // the technical name, as stored in the YAML
    row.appendChild(label);

    row.appendChild(
      renderValueOrRefEditor(step.params[key], {
        owner: step,
        defaultValue,
        isUserId: isUserIdField(step.module, key),
        isCalendarId: isCalendarIdField(step.module, key),
        isLabelId: isLabelIdField(step.module, key),
        isStackId: isStackIdField(step.module, key),
        isBoardId: isBoardIdField(step.module, key),
        isActionName: isActionNameField(step.module, key),
        // copy_card's target column belongs to its own target board, not the workflow's.
        stackBoardIdOf: step.module === 'copy_card'
          ? () => (step.params.target_board_id || {}).value
          : undefined,
        formatHint: formatHintFor(step.module, key),
        germanDateTime: isGermanDateTimeField(step.module, key),
      })
    );

    const example = (module.param_help || {})[key];
    if (example) {
      const exampleEl = document.createElement('div');
      exampleEl.className = 'param-example muted';
      exampleEl.textContent = example;
      row.appendChild(exampleEl);
    }

    return row;
  }

  const CALCULATE_OPS = [
    ['add', '+'],
    ['subtract', '−'],
    ['multiply', '×'],
    ['divide', '÷'],
  ];

  const CALCULATE_OP_NAMES = {
    add: 'Addieren', subtract: 'Subtrahieren', multiply: 'Multiplizieren', divide: 'Dividieren',
  };

  // calculate reads as one line - left value, operation dropdown, right value
  // - instead of three stacked param rows.
  function renderCalculateRow(step) {
    const row = document.createElement('div');
    row.className = 'calc-row';
    row.appendChild(renderValueOrRefEditor(step.params.left, {
      owner: step,
      defaultValue: modulesByName.calculate.input.left,
    }));

    const opEntry = step.params.op;
    if (opEntry.source === 'ref') {
      row.appendChild(renderValueOrRefEditor(opEntry, { owner: step }));
    } else {
      const opSelect = document.createElement('select');
      // A hand-written op outside the four known ones is shown as-is instead
      // of silently displaying "+" while still saving the unknown value.
      const ops = CALCULATE_OPS.some(([value]) => value === opEntry.value)
        ? CALCULATE_OPS
        : [...CALCULATE_OPS, [opEntry.value, String(opEntry.value)]];
      ops.forEach(([value, text]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = text;
        option.title = CALCULATE_OP_NAMES[value] || '';
        option.selected = opEntry.value === value;
        opSelect.appendChild(option);
      });
      opSelect.addEventListener('change', () => {
        opEntry.value = opSelect.value;
      });
      row.appendChild(opSelect);
    }

    row.appendChild(renderValueOrRefEditor(step.params.right, {
      owner: step,
      defaultValue: modulesByName.calculate.input.right,
    }));
    return row;
  }

  function renderActionNode(step, list, index) {
    const wrapper = document.createElement('div');
    wrapper.className = 'step';

    const header = document.createElement('div');
    header.className = 'step-header';

    const number = document.createElement('span');
    number.className = 'step-number';
    number.textContent = step.displayNumber + '.';
    header.appendChild(number);

    const moduleSelect = document.createElement('select');
    moduleSelect.className = 'module-select';
    moduleNames.forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = moduleLabel(name);
      option.title = name;
      option.selected = name === step.module;
      moduleSelect.appendChild(option);
    });
    moduleSelect.addEventListener('change', () => {
      step.module = moduleSelect.value;
      step.params = defaultParamsFor(step.module);
      render();
    });
    header.appendChild(moduleSelect);

    const infoBtn = document.createElement('button');
    infoBtn.type = 'button';
    infoBtn.className = 'icon-btn info-btn';
    infoBtn.textContent = 'i';
    infoBtn.title = 'Welche Werte liefert dieser Schritt?';
    infoBtn.setAttribute('aria-label', infoBtn.title);
    infoBtn.setAttribute('aria-expanded', step.showOutputs ? 'true' : 'false');
    header.appendChild(infoBtn);

    header.appendChild(renderMoveRemoveControls(list, index));
    wrapper.appendChild(header);

    const module = modulesByName[step.module];
    if (module && module.description) {
      const description = document.createElement('p');
      description.className = 'step-description muted';
      description.textContent = module.description;
      wrapper.appendChild(description);
    }

    const outputsEl = renderOutputsInfo(step, module);
    outputsEl.hidden = !step.showOutputs;
    infoBtn.addEventListener('click', () => {
      step.showOutputs = !step.showOutputs; // UI state only - not part of the saved workflow
      outputsEl.hidden = !step.showOutputs;
      infoBtn.setAttribute('aria-expanded', step.showOutputs ? 'true' : 'false');
    });
    wrapper.appendChild(outputsEl);
    const paramsEl = document.createElement('div');
    paramsEl.className = 'params';

    if (module) {
      const keys = Object.keys(module.input || {});
      if (step.module === 'calculate' && step.params.left && step.params.op && step.params.right) {
        paramsEl.appendChild(renderCalculateRow(step));
      } else {
        keys.forEach((key) => {
          paramsEl.appendChild(renderParamRow(step, key, module.input[key]));
        });
      }
      if (keys.length === 0) {
        const none = document.createElement('p');
        none.className = 'muted';
        none.textContent = 'Dieses Modul benötigt keine Parameter.';
        paramsEl.appendChild(none);
      }
    }
    wrapper.appendChild(paramsEl);

    // Rarely needed, so out of the way: the name later steps use to refer to
    // this step's output (the "Wert übernehmen" list shows it as "Schritt N").
    const advanced = document.createElement('details');
    advanced.className = 'step-advanced';
    const summary = document.createElement('summary');
    summary.textContent = 'Erweitert';
    advanced.appendChild(summary);
    const idLabel = document.createElement('label');
    idLabel.textContent = 'Schritt-Id (technischer Name für Verweise) ';
    const idInput = document.createElement('input');
    idInput.type = 'text';
    idInput.value = step.id;
    idInput.addEventListener('input', () => {
      step.id = idInput.value;
    });
    idLabel.appendChild(idInput);
    advanced.appendChild(idLabel);
    wrapper.appendChild(advanced);

    return wrapper;
  }

  // A <ul> of "name – description": the real field name (as it appears in the
  // YAML, e.g. what create_action_link's "Felder der Action" needs) followed by
  // the short German description, and the help text if the field has one.
  function renderFieldList(names, labels, help) {
    const listEl = document.createElement('ul');
    names.forEach((name) => {
      const item = document.createElement('li');
      const code = document.createElement('code');
      code.textContent = name;
      item.appendChild(code);
      const description = labels[name] || '';
      item.appendChild(document.createTextNode(description ? ' – ' + description : ''));
      if (help && help[name]) {
        const helpEl = document.createElement('div');
        helpEl.className = 'muted small';
        helpEl.textContent = help[name];
        item.appendChild(helpEl);
      }
      listEl.appendChild(item);
    });
    return listEl;
  }

  function addParagraph(box, text, className) {
    const p = document.createElement('p');
    if (className) {
      p.className = className;
    }
    p.textContent = text;
    box.appendChild(p);
  }

  // The "i" box of a step: which fields it takes (real names) and which
  // values it hands on to later steps.
  function renderOutputsInfo(step, module) {
    const box = document.createElement('div');
    box.className = 'step-outputs';
    const inputs = Object.keys((module && module.input) || {});
    const outputs = Object.keys((module && module.output) || {});

    addParagraph(box, inputs.length === 0 ? 'Dieser Schritt hat keine Eingabefelder.' : 'Eingabefelder:');
    if (inputs.length > 0) {
      box.appendChild(renderFieldList(inputs, module.param_labels || {}, module.param_help || {}));
    }

    // "Einmal-Link erstellen" takes another action's fields as a JSON object:
    // show which ones the chosen action needs.
    const chosen = step.module === 'create_action_link' && step.params.action && step.params.action.source === 'literal'
      ? modulesByName[step.params.action.value]
      : null;
    if (chosen) {
      const chosenInputs = Object.keys(chosen.input || {});
      addParagraph(box, 'Felder der gewählten Action „' + moduleLabel(chosen.name) + '" (für „Felder der Action"):');
      if (chosenInputs.length > 0) {
        box.appendChild(renderFieldList(chosenInputs, chosen.param_labels || {}, chosen.param_help || {}));
      } else {
        addParagraph(box, 'Diese Action hat keine Felder.', 'muted');
      }
    }

    addParagraph(box, outputs.length === 0
      ? 'Dieser Schritt liefert keine Werte für spätere Schritte.'
      : 'Liefert für spätere Schritte:');
    if (outputs.length > 0) {
      box.appendChild(renderFieldList(outputs, module.output_labels || {}, null));
      addParagraph(box, 'Verwenden: in einem späteren Schritt bei einem Feld „Wert übernehmen" wählen, dann '
        + '„Schritt ' + step.displayNumber + ': ' + moduleLabel(step.module) + '" und das gewünschte Feld.', 'muted');
    }
    if (step.module === 'set_variable') {
      addParagraph(box, 'Außerdem steht der Wert in späteren Schritten unter „Variablen" und in Texten als $Name zur Verfügung.', 'muted');
    }
    return box;
  }

  function renderMoveRemoveControls(list, index) {
    const controls = document.createElement('span');
    controls.className = 'step-controls';
    [
      ['↑', 'Nach oben', () => moveNode(list, index, -1), index === 0],
      ['↓', 'Nach unten', () => moveNode(list, index, 1), index === list.length - 1],
      ['✕', 'Schritt entfernen', () => removeNode(list, index), false],
    ].forEach(([text, title, onClick, disabled]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'icon-btn' + (text === '✕' ? ' danger' : '');
      button.textContent = text;
      button.title = title;
      button.setAttribute('aria-label', title);
      button.disabled = disabled;
      button.addEventListener('click', onClick);
      controls.appendChild(button);
    });
    return controls;
  }

  function renderIfNode(node, list, index) {
    const wrapper = document.createElement('div');
    wrapper.className = 'step if-step';

    const header = document.createElement('div');
    header.className = 'step-header';

    const label = document.createElement('strong');
    label.textContent = node.displayNumber + '. Wenn';
    header.appendChild(label);

    header.appendChild(renderMoveRemoveControls(list, index));
    wrapper.appendChild(header);

    // Left value, operator and right value each get their own line.
    const conditionEl = document.createElement('div');
    conditionEl.className = 'if-condition';
    conditionEl.appendChild(renderValueOrRefEditor(node.condition.left, { owner: node }));

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
    const opRow = document.createElement('div');
    opRow.appendChild(opSelect);
    conditionEl.appendChild(opRow);

    conditionEl.appendChild(renderValueOrRefEditor(node.condition.right, { owner: node }));
    wrapper.appendChild(conditionEl);

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
    addStepBtn.title = 'Eine weitere Action an dieser Stelle anhängen';
    addStepBtn.addEventListener('click', () => {
      list.push(makeActionNode());
      render();
    });
    controls.appendChild(addStepBtn);

    const addIfBtn = document.createElement('button');
    addIfBtn.type = 'button';
    addIfBtn.textContent = '+ Wenn/Sonst';
    addIfBtn.title = 'Eine Bedingung einfügen: Schritte nur ausführen, wenn sie zutrifft';
    addIfBtn.addEventListener('click', () => {
      list.push(makeIfNode());
      render();
    });
    controls.appendChild(addIfBtn);

    container.appendChild(controls);
  }

  function removeNode(list, index) {
    const node = list[index];
    const hasContent = node.kind === 'if' ? node.then.length + node.else.length > 0 : false;
    if (hasContent && !confirm('Diesen Wenn/Sonst-Block samt allen Schritten darin entfernen?')) {
      return;
    }
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

  // Display numbers ("2", "3.1", "3.s1" for an else branch) - assigned
  // before rendering, so every "Wert übernehmen" list can name any step.
  function assignNumbers(list, prefix) {
    list.forEach((node, index) => {
      node.displayNumber = prefix + (index + 1);
      if (node.kind === 'if') {
        assignNumbers(node.then, node.displayNumber + '.');
        assignNumbers(node.else, node.displayNumber + '.s');
      }
    });
  }

  function render() {
    assignNumbers(state.steps, '');
    stepsEl.innerHTML = '';
    renderStepList(state.steps, stepsEl);
    markDirty();
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

  function shownText(fieldEl) {
    const input = fieldEl.querySelector('input');
    return input ? input.value.trim() : '';
  }

  function collectPayload() {
    if (!instanceEl.value) {
      throw new Error('Bitte Instanz auswählen.');
    }
    const boardId = parseId(boardEl.value, 'Board');
    if (boardId === null) {
      throw new Error('Bitte ein Board aus der Liste auswählen.');
    }
    if (!nameEl.value.trim()) {
      throw new Error('Bitte einen Namen für den Workflow angeben.');
    }
    if (!/^[a-z0-9-]+$/.test(idEl.value.trim())) {
      const advanced = idEl.closest('details');
      if (advanced) {
        advanced.open = true;
      }
      throw new Error('Die Id (unter „Erweitert") darf nur a-z, 0-9 und - enthalten.');
    }
    if (state.steps.length === 0) {
      throw new Error('Bitte mindestens einen Schritt hinzufügen.');
    }
    if (stepsEl.querySelector('textarea.invalid')) {
      throw new Error('Ein JSON-Feld enthält ungültiges JSON - bitte prüfen.');
    }
    if (stepsEl.querySelector('input.invalid')) {
      throw new Error('Ein Feld hat keinen gültigen Wert (Datum TT.MM.JJJJ hh:mm bzw. Auswahl aus der Liste) - bitte prüfen.');
    }

    const payload = {
      mode: isEditMode ? 'edit' : 'create',
      instance: instanceEl.value,
      board_id: boardId,
      name: nameEl.value.trim(),
      id: idEl.value.trim(),
      folder: (document.getElementById('folder') || { value: '' }).value,
      // Display names for the overview, so it needn't ask Nextcloud for them.
      board_title: shownText(boardFieldEl),
      steps: collectSteps(state.steps, new Set()),
    };

    if (triggerKindEl.value === 'schedule') {
      if (!scheduleTimeEl.value) {
        throw new Error('Bitte eine Uhrzeit für den Zeitplan angeben.');
      }
      payload.schedule = {
        time: scheduleTimeEl.value,
        weekdays: weekdayCheckboxes.filter((cb) => cb.checked).map((cb) => Number(cb.value)),
      };
    } else {
      payload.stack_id = parseId(stackEl.value, 'Spalte');
      payload.stack_title = payload.stack_id === null ? '' : shownText(stackFieldEl);
      payload.event = document.getElementById('event-type').value;
    }

    return payload;
  }

  document.getElementById('workflow-form').addEventListener('submit', (event) => {
    hideError();
    try {
      const payload = collectPayload();
      document.getElementById('payload').value = JSON.stringify(payload);
      submitting = true;
    } catch (e) {
      event.preventDefault();
      showError(e.message);
    }
  });

  // -- edit mode: restore an existing workflow's data into the form ----------

  // Inverse of operandValue() above - turns a stored literal/{"$ref": ...}
  // value back into the internal {source, value, refStep, refField} shape.
  function toInternalOperand(value) {
    if (value !== null && typeof value === 'object' && !Array.isArray(value)
        && Object.keys(value).length === 1 && typeof value.$ref === 'string') {
      const dot = value.$ref.indexOf('.');
      return {
        source: 'ref',
        refStep: dot === -1 ? value.$ref : value.$ref.slice(0, dot),
        refField: dot === -1 ? '' : value.$ref.slice(dot + 1),
      };
    }
    return { source: 'literal', value: value === undefined ? null : value };
  }

  // Inverse of collectSteps() - turns a stored step (action or if/then/else)
  // back into the internal tree shape render()/collectSteps() expect.
  function toInternalStep(raw) {
    if (raw.type === 'if') {
      const condition = raw.condition || {};
      return {
        kind: 'if',
        condition: {
          left: toInternalOperand(condition.left),
          op: condition.op,
          right: toInternalOperand(condition.right),
        },
        then: (raw.then || []).map(toInternalStep),
        else: (raw.else || []).map(toInternalStep),
      };
    }
    // Start from the module's defaults so a param omitted in a hand-written
    // YAML (e.g. date_offset's optional base) still gets an editor row.
    const params = defaultParamsFor(raw.module);
    Object.keys(raw.params || {}).forEach((key) => {
      params[key] = toInternalOperand(raw.params[key]);
    });
    return { kind: 'action', id: raw.id || 'step' + stepCounter++, module: raw.module, params };
  }

  function initializeForEdit(existing) {
    instanceEl.value = existing.nextcloud_instance;
    nameEl.value = existing.name;
    idEl.value = existing.id;
    idManuallyEdited = true; // the id is fixed in edit mode - never auto-slugify over it

    const schedule = existing.trigger.schedule;
    if (schedule) {
      triggerKindEl.value = 'schedule';
      scheduleTimeEl.value = schedule.time;
      (schedule.weekdays || []).forEach((iso) => {
        const cb = weekdayCheckboxes.find((c) => Number(c.value) === iso);
        if (cb) {
          cb.checked = true;
        }
      });
    } else {
      triggerKindEl.value = 'event';
      document.getElementById('event-type').value = existing.trigger.event;
    }
    applyTriggerKind();

    state.steps = (existing.actions || []).map(toInternalStep);
    render();

    loadBoardsFor(existing.board_id, schedule ? null : existing.trigger.stack_id ?? null);
  }

  // The "i" above the steps: the fields of the card that triggered the
  // workflow (the reserved "card" source), same format as a step's box.
  const cardInfoBtn = document.getElementById('card-info-btn');
  const cardInfoEl = document.getElementById('card-info');
  if (cardInfoBtn && cardInfoEl) {
    addParagraph(cardInfoEl, 'Ohne eigenen Schritt verfügbar - die Felder der Karte, die den Workflow ausgelöst hat:');
    cardInfoEl.appendChild(renderFieldList(
      CARD_FIELDS.map(([name]) => name),
      Object.fromEntries(CARD_FIELDS),
      null
    ));
    addParagraph(cardInfoEl, 'Verwenden: bei einem Feld „Wert übernehmen" wählen, dann „Karte" und das gewünschte Feld '
      + '(in der YAML: {$ref: card.title}). Die Werte kommen direkt aus der Deck-API - weitere Felder über „Anderes Feld …".', 'muted');
    addParagraph(cardInfoEl, 'Bei einem Zeitplan-Auslöser gibt es keine auslösende Karte - diese Werte sind dann leer.', 'muted');
    cardInfoBtn.addEventListener('click', () => {
      cardInfoEl.hidden = !cardInfoEl.hidden;
      cardInfoBtn.setAttribute('aria-expanded', cardInfoEl.hidden ? 'false' : 'true');
    });
  }

  const existingDataEl = document.getElementById('existing-workflow-data');
  const isEditMode = existingDataEl !== null;
  if (isEditMode) {
    initializeForEdit(JSON.parse(existingDataEl.textContent));
  } else {
    state.steps.push(makeActionNode());
    render();
  }
  const formEl = document.getElementById('workflow-form');
  formEl.addEventListener('input', markDirty);
  formEl.addEventListener('change', markDirty);
  loaded = true;
})();
