// Generated application frontend: plain JavaScript, no dependencies, no inline code.
// The DOM is built with createElement/textContent only (never innerHTML), so record
// values cannot inject markup. Writes are same-origin JSON requests.
'use strict';

(function () {
  const state = { schema: null, i18n: null, lang: null, entity: null, records: [], options: {}, editing: null, pendingDelete: null };
  const STORAGE_KEY = 'app.lang';
  const byId = (id) => document.getElementById(id);

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === false || value === null || value === undefined) continue;
      if (key === 'text') node.textContent = String(value);
      else if (key === 'className') node.className = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? '' : String(value));
    }
    for (const child of children || []) node.append(child);
    return node;
  }

  function strings() { return state.i18n[state.lang]; }
  function ui(key, vars) {
    let text = strings().ui[key] || state.i18n.en?.ui?.[key] || key;
    for (const [name, value] of Object.entries(vars || {})) text = text.split('{' + name + '}').join(String(value));
    return text;
  }
  function entityText(entity, kind) { return strings().entities[entity.name][kind]; }
  function fieldText(entity, name) { return strings().fields[entity.name][name] || name; }
  function valueText(entity, field, value) {
    const values = strings().values[entity.name] || {};
    return (values[field] && values[field][value]) || value;
  }
  function errorText(code) { return strings().errors[code] || strings().errors.invalid || code; }

  async function api(method, path, body) {
    const options = { method, headers: { Accept: 'application/json' }, credentials: 'same-origin' };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    const response = await fetch(path, options);
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) {
      const error = new Error((data && data.error && data.error.code) || String(response.status));
      error.status = response.status;
      error.data = data && data.error;
      throw error;
    }
    return data;
  }

  function pickLanguage() {
    const locales = state.schema.app.locales;
    let saved = null;
    try { saved = window.localStorage.getItem(STORAGE_KEY); } catch (_) { saved = null; }
    return locales.includes(saved) ? saved : state.schema.app.default_locale;
  }

  function applyLanguage() {
    const root = document.documentElement;
    root.lang = state.lang;
    root.dir = strings().dir;
    document.title = strings().app.title;
    byId('app-title').textContent = strings().app.title;
    byId('skip-link').textContent = ui('skip');
    byId('lang-label').textContent = ui('language');
    byId('entity-nav').setAttribute('aria-label', ui('sections'));
    byId('footer-note').textContent = ui('footer');
    const buttons = byId('lang-buttons');
    buttons.replaceChildren();
    for (const locale of state.schema.app.locales) {
      const pressed = locale === state.lang;
      buttons.append(el('button', {
        type: 'button', lang: locale, 'aria-pressed': pressed ? 'true' : 'false', 'data-locale': locale,
        text: state.i18n[locale].name, onclick: () => setLanguage(locale),
      }));
    }
  }

  function setLanguage(locale) {
    if (!state.schema.app.locales.includes(locale)) return;
    state.lang = locale;
    try { window.localStorage.setItem(STORAGE_KEY, locale); } catch (_) { /* storage may be unavailable */ }
    applyLanguage();
    renderNav();
    renderEntity();
  }

  function renderNav() {
    const nav = byId('entity-nav');
    nav.replaceChildren();
    for (const entity of state.schema.entities) {
      nav.append(el('button', {
        type: 'button', 'data-entity': entity.name, text: entityText(entity, 'plural'),
        'aria-current': state.entity === entity ? 'page' : false, onclick: () => selectEntity(entity.name),
      }));
    }
  }

  function recordLabel(entity, record) {
    if (entity.label_field && record[entity.label_field]) return String(record[entity.label_field]);
    return '#' + record.id;
  }

  async function selectEntity(name) {
    state.entity = state.schema.entities.find((entity) => entity.name === name);
    state.editing = null;
    state.pendingDelete = null;
    message('', '');
    renderNav();
    await reload();
  }

  async function reload() {
    const entity = state.entity;
    const main = byId('main');
    main.setAttribute('aria-busy', 'true');
    try {
      const related = [...entity.references, ...entity.links];
      const lists = await Promise.all(related.map((rel) => {
        const target = state.schema.entities.find((item) => item.name === rel.entity);
        return api('GET', '/api/' + target.collection + '?limit=500').then((page) => [rel.field, target, page.items]);
      }));
      state.options = {};
      for (const [field, target, items] of lists) state.options[field] = { target, items };
      const page = await api('GET', '/api/' + entity.collection + '?limit=500');
      state.records = page.items;
    } catch (error) {
      message('', ui('loadError'));
      state.records = [];
    }
    renderEntity();
    main.removeAttribute('aria-busy');
  }

  function message(status, alert) {
    byId('status').textContent = status || '';
    byId('alert').textContent = alert || '';
  }

  function control(entity, spec, value) {
    const id = 'f-' + spec.name;
    const describedBy = id + '-error';
    const common = { id, name: spec.name, 'aria-describedby': describedBy };
    if (spec.required) common['aria-required'] = 'true';
    let input;
    if (spec.kind === 'reference' || spec.kind === 'link') {
      const option = state.options[spec.name] || { target: null, items: [] };
      input = el('select', { ...common, multiple: spec.kind === 'link', required: spec.required && spec.kind === 'reference' });
      if (spec.kind === 'reference') input.append(el('option', { value: '', text: ui('choose') }));
      for (const item of option.items) {
        const selected = spec.kind === 'link' ? (value || []).includes(item.id) : value === item.id;
        input.append(el('option', { value: String(item.id), text: recordLabel(option.target, item), selected }));
      }
    } else if (spec.type === 'enum') {
      input = el('select', { ...common, required: spec.required });
      input.append(el('option', { value: '', text: ui('choose') }));
      for (const choice of spec.values) {
        input.append(el('option', { value: choice, text: valueText(entity, spec.name, choice), selected: value === choice }));
      }
    } else if (spec.type === 'bool') {
      input = el('input', { ...common, type: 'checkbox' });
      input.checked = value === undefined || value === null ? Boolean(spec.default) : Boolean(value);
    } else if (spec.type === 'text' && (spec.max || 0) > 500) {
      input = el('textarea', { ...common, rows: 4, maxlength: spec.max, required: spec.required });
      input.value = value || '';
    } else {
      const types = { text: 'text', email: 'email', int: 'number', number: 'number', date: 'date', datetime: 'datetime-local' };
      input = el('input', {
        ...common, type: types[spec.type] || 'text', required: spec.required,
        maxlength: ['text', 'email'].includes(spec.type) ? spec.max : null,
        step: spec.type === 'int' ? '1' : spec.type === 'number' ? 'any' : null,
        min: spec.min, max: ['int', 'number'].includes(spec.type) ? spec.max : null,
      });
      let shown = value === null || value === undefined ? '' : String(value);
      if (spec.type === 'datetime' && shown) shown = shown.slice(0, 16);
      input.value = shown;
    }
    const label = el('label', { for: id, text: fieldText(entity, spec.name) });
    const wrapper = el('div', { className: spec.type === 'bool' ? 'field checkbox' : 'field' }, [label]);
    if (spec.required) wrapper.append(el('span', { className: 'req', 'aria-hidden': 'true', text: '*' }));
    wrapper.append(input, el('span', { id: describedBy, className: 'error' }));
    return wrapper;
  }

  function specs(entity) {
    const rows = entity.fields.map((field) => ({ ...field, kind: 'field' }));
    for (const ref of entity.references) rows.push({ name: ref.field, kind: 'reference', required: ref.required });
    for (const link of entity.links) rows.push({ name: link.field, kind: 'link', required: false });
    return rows;
  }

  function readValue(form, spec) {
    const input = form.elements.namedItem(spec.name);
    if (spec.kind === 'link') return Array.from(input.selectedOptions).map((option) => Number(option.value));
    if (spec.kind === 'reference') return input.value ? Number(input.value) : null;
    if (spec.type === 'bool') return input.checked;
    const raw = input.value;
    if (raw === '') return null;
    if (spec.type === 'int') return Number.parseInt(raw, 10);
    if (spec.type === 'number') return Number(raw);
    if (spec.type === 'datetime') return raw.length === 16 ? raw + ':00' : raw;
    return raw;
  }

  function renderForm(entity) {
    const form = byId('record-form');
    form.replaceChildren();
    const current = state.editing ? state.records.find((record) => record.id === state.editing) : null;
    byId('form-title').textContent = current
      ? ui('editTitle', { entity: entityText(entity, 'singular'), label: recordLabel(entity, current) })
      : ui('newTitle', { entity: entityText(entity, 'singular') });
    for (const spec of specs(entity)) form.append(control(entity, spec, current ? current[spec.name] : undefined));
    const actions = el('div', { className: 'actions' }, [el('button', { type: 'submit', className: 'primary', text: ui('save') })]);
    if (current) {
      actions.append(el('button', { type: 'button', text: ui('cancel'), onclick: () => { state.editing = null; renderEntity(); } }));
    }
    form.append(actions);
    form.onsubmit = (event) => { event.preventDefault(); submit(entity, form); };
  }

  async function submit(entity, form) {
    const body = {};
    for (const spec of specs(entity)) {
      const value = readValue(form, spec);
      if (value !== null || spec.kind !== 'field' || !spec.required) body[spec.name] = value;
    }
    for (const node of form.querySelectorAll('[aria-invalid]')) node.removeAttribute('aria-invalid');
    for (const node of form.querySelectorAll('.error')) node.textContent = '';
    const editing = state.editing;
    try {
      if (editing) await api('PUT', '/api/' + entity.collection + '/' + editing, body);
      else await api('POST', '/api/' + entity.collection, body);
      state.editing = null;
      await reload();
      message(ui('saved', { entity: entityText(entity, 'singular') }), '');
    } catch (error) {
      const fields = (error.data && error.data.fields) || {};
      let first = null;
      for (const [name, code] of Object.entries(fields)) {
        const input = form.elements.namedItem(name);
        const slot = byId('f-' + name + '-error');
        if (input && slot) {
          input.setAttribute('aria-invalid', 'true');
          slot.textContent = errorText(code);
          first = first || input;
        }
      }
      message('', errorText(error.message));
      if (first) first.focus();
    }
  }

  async function remove(entity, record) {
    try {
      await api('DELETE', '/api/' + entity.collection + '/' + record.id);
      state.pendingDelete = null;
      await reload();
      message(ui('deleted', { entity: entityText(entity, 'singular') }), '');
    } catch (error) {
      state.pendingDelete = null;
      renderEntity();
      message('', errorText(error.message));
    }
  }

  function cellText(entity, spec, record) {
    const value = record[spec.name];
    if (value === null || value === undefined || (Array.isArray(value) && !value.length)) return '—';
    if (spec.kind === 'reference' || spec.kind === 'link') {
      const option = state.options[spec.name];
      const ids = Array.isArray(value) ? value : [value];
      return ids.map((id) => {
        const item = option && option.items.find((row) => row.id === id);
        return item ? recordLabel(option.target, item) : '#' + id;
      }).join(strings().dir === 'rtl' ? '، ' : ', ');
    }
    if (spec.type === 'bool') return value ? ui('yes') : ui('no');
    if (spec.type === 'enum') return valueText(entity, spec.name, value);
    return String(value);
  }

  function renderTable(entity) {
    const table = byId('records');
    byId('list-title').textContent = entityText(entity, 'plural');
    byId('records-caption').textContent = entityText(entity, 'plural');
    const head = table.tHead;
    const body = table.tBodies[0];
    head.replaceChildren();
    body.replaceChildren();
    const columns = specs(entity);
    head.append(el('tr', {}, [
      ...columns.map((spec) => el('th', { scope: 'col', text: fieldText(entity, spec.name) })),
      el('th', { scope: 'col', text: ui('actions') }),
    ]));
    for (const record of state.records) {
      const label = recordLabel(entity, record);
      const actions = el('td', { className: 'row-actions' });
      if (state.pendingDelete === record.id) {
        const confirm = el('button', { type: 'button', className: 'danger', text: ui('confirmDelete'),
          'aria-label': ui('confirmDelete') + ': ' + label, onclick: () => remove(entity, record) });
        actions.append(confirm, el('button', { type: 'button', text: ui('cancel'),
          'aria-label': ui('cancel') + ': ' + label, onclick: () => { state.pendingDelete = null; renderEntity(); } }));
        window.setTimeout(() => confirm.focus(), 0);
      } else {
        actions.append(
          el('button', { type: 'button', text: ui('edit'), 'aria-label': ui('edit') + ': ' + label,
            onclick: () => { state.editing = record.id; state.pendingDelete = null; renderEntity(); byId('record-form').querySelector('input, select, textarea')?.focus(); } }),
          el('button', { type: 'button', className: 'danger', text: ui('delete'), 'aria-label': ui('delete') + ': ' + label,
            onclick: () => { state.pendingDelete = record.id; renderEntity(); } }),
        );
      }
      body.append(el('tr', { 'data-id': record.id }, [
        ...columns.map((spec) => el('td', { text: cellText(entity, spec, record) })),
        actions,
      ]));
    }
    const empty = byId('empty');
    empty.hidden = state.records.length > 0;
    empty.textContent = ui('empty');
  }

  function renderEntity() {
    const entity = state.entity;
    if (!entity) return;
    byId('entity-title').textContent = entityText(entity, 'plural');
    renderForm(entity);
    renderTable(entity);
  }

  async function boot() {
    try {
      const [schema, i18n] = await Promise.all([api('GET', '/api/schema'), api('GET', '/static/i18n.json')]);
      state.schema = schema;
      state.i18n = i18n;
      state.lang = pickLanguage();
      applyLanguage();
      byId('skip-link').addEventListener('click', (event) => { event.preventDefault(); byId('main').focus(); });
      await selectEntity(schema.entities[0].name);
      document.body.setAttribute('data-ready', 'true');
    } catch (error) {
      byId('alert').textContent = 'The application could not start / تعذّر تشغيل التطبيق';
    }
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
