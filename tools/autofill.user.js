// ==UserScript==
// @name         apply — field pack autofill
// @namespace    https://github.com/ajaiupadhyaya
// @version      0.1.0
// @description  Fills labelled fields on an application portal from a local field pack. Fills only; never clicks, never submits.
// @author       AJ Upadhyaya
// @match        *://*/*
// @exclude      *://*.joinhandshake.com/*
// @exclude      *://joinhandshake.com/*
// @connect      localhost
// @grant        GM_xmlhttpRequest
// @run-at       document-idle
// ==/UserScript==

/*
 * This is optional and the least important part of apply. The copy-button list
 * in the dashboard covers most of the value with none of the fragility; install
 * this only if you are filling the same Workday form for the tenth time.
 *
 * What it will not do, by construction:
 *   - click anything, ever, including Next, Save, and Submit
 *   - touch a file input, a password field, or anything inside a form whose
 *     submit control currently has focus
 *   - run on Handshake
 *   - send anything anywhere: it reads from 127.0.0.1 and writes to the page
 *
 * Every field it fills is outlined in amber so you can see exactly what it
 * touched before you read the form yourself.
 */

(function () {
  'use strict';

  const ORIGIN = 'http://127.0.0.1:8787';
  const HIGHLIGHT = '2px solid #d99a2b';

  const NEVER_FILL = new Set(['file', 'password', 'hidden', 'submit', 'button', 'image', 'reset']);

  function norm(text) {
    return (text || '').toLowerCase().replace(/[\s ]+/g, ' ').replace(/[*:?]/g, '').trim();
  }

  /** The visible label for a control, by every route a portal might use. */
  function labelFor(el) {
    const bits = [];
    if (el.id) {
      const tag = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (tag) bits.push(tag.textContent);
    }
    const wrapping = el.closest('label');
    if (wrapping) bits.push(wrapping.textContent);
    if (el.getAttribute('aria-label')) bits.push(el.getAttribute('aria-label'));
    const describedBy = el.getAttribute('aria-labelledby');
    if (describedBy) {
      describedBy.split(/\s+/).forEach((id) => {
        const node = document.getElementById(id);
        if (node) bits.push(node.textContent);
      });
    }
    if (el.placeholder) bits.push(el.placeholder);
    if (el.name) bits.push(el.name.replace(/[-_]+/g, ' '));
    return bits.map(norm).filter(Boolean);
  }

  function fillable(el) {
    if (el.disabled || el.readOnly) return false;
    if (el.tagName === 'INPUT' && NEVER_FILL.has(el.type)) return false;
    if (el.value && el.value.trim()) return false;      // never overwrite
    // If the person is mid-submit, stay out of the way entirely.
    const form = el.closest('form');
    const active = document.activeElement;
    if (form && active && form.contains(active) &&
        (active.type === 'submit' || active.tagName === 'BUTTON')) return false;
    return true;
  }

  function setValue(el, value) {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(proto.prototype, 'value').set;
    setter.call(el, value);                              // React-friendly
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.style.outline = HIGHLIGHT;
    el.style.outlineOffset = '1px';
  }

  function apply(pack) {
    const controls = [...document.querySelectorAll('input, textarea, select')];
    let filled = 0;

    for (const field of pack.fields) {
      const wanted = field.labels.map(norm);
      for (const el of controls) {
        if (!fillable(el)) continue;
        const labels = labelFor(el);
        const hit = labels.some((l) => wanted.some((w) => l === w || l.includes(w)));
        if (!hit) continue;

        if (el.tagName === 'SELECT') {
          const option = [...el.options].find(
            (o) => norm(o.textContent) === norm(field.value) || o.value === field.value);
          if (!option) continue;
          el.value = option.value;
          el.dispatchEvent(new Event('change', { bubbles: true }));
          el.style.outline = HIGHLIGHT;
        } else {
          setValue(el, field.value);
        }
        filled += 1;
        break;
      }
    }
    banner(`Filled ${filled} field${filled === 1 ? '' : 's'}, outlined in amber. ` +
           `Nothing was clicked. Read the form before you submit it.`);
  }

  function banner(text) {
    const strip = document.createElement('div');
    strip.textContent = text;
    strip.style.cssText =
      'position:fixed;left:0;right:0;top:0;z-index:2147483647;padding:.6rem 1rem;' +
      'background:#191c19;color:#f1f3ef;font:14px/1.4 ui-sans-serif,system-ui,sans-serif;';
    document.body.appendChild(strip);
    setTimeout(() => strip.remove(), 6000);
  }

  function load(slug) {
    GM_xmlhttpRequest({
      method: 'GET',
      url: `${ORIGIN}/file/${encodeURIComponent(slug)}/fieldpack.json`,
      onload: (r) => {
        if (r.status !== 200) return banner('apply: no field pack for that slug.');
        try {
          apply(JSON.parse(r.responseText));
        } catch (e) {
          banner('apply: could not read the field pack.');
        }
      },
      onerror: () => banner('apply: is `apply serve` running?'),
    });
  }

  // Deliberately manual. Nothing fills until you ask for it by slug.
  window.applyFill = load;
  console.info('apply: type applyFill("<slug>") to fill this form. ' +
               'This script fills only — it never clicks or submits.');
})();
