// The console's five behaviours, in plain JavaScript against HTMX.
//
// WHAT: the toast timer, dialog dismissal, the copy button, showing the field group
//       a select chose, and the failure a request raises when it does not come back —
//       stated under the header, and inside the dialog as well when one is open in
//       front of it.
// WHY:  design/README.md asks for a toast that auto-dismisses and shows one at a
//       time, dialogs that close on the backdrop, and a copy button that works. None
//       of those is expressible in HTML alone, and the stack rule (CLAUDE.md) is
//       Jinja2 + HTMX with no framework and no bundler — so this is the whole of the
//       panel's client-side code, and it is deliberately small enough to read.
// HOW:  delegated listeners on `document`, so nothing has to be re-bound after HTMX
//       swaps a fragment in. Every element it touches is addressed by a class this
//       repository's own templates set.
//
// Nothing here logs, reports, measures or fetches. The one value it handles that
// matters is the subscription URL in the link dialog: it is read from the DOM and
// written to the clipboard, and it never becomes a URL, an attribute or a message.

(() => {
  "use strict";

  // design/README.md: 2200ms, one at a time — "a new toast clears the pending timer".
  const TOAST_MS = 2200;
  let toastTimer = null;

  const slot = (name) => document.querySelector("." + name);

  function armToast() {
    const host = slot("toast-slot");
    if (!host) return;
    clearTimeout(toastTimer);
    if (!host.firstElementChild) return;
    toastTimer = setTimeout(() => { host.innerHTML = ""; }, TOAST_MS);
  }

  function closeDialog() {
    const host = slot("dialog-slot");
    if (host) host.innerHTML = "";
  }

  // A failure element: the accent-weighted frame and the word that says what it is.
  // The same shape is used under the header and inside a dialog, so a failure looks
  // the same wherever the operator meets it — see .banner-failure in app.css, and
  // note that the ordinary notice (`.banner` alone) is deliberately quieter. The two
  // were identical, which is how a failure came to read as an informational message.
  function failure(text) {
    const box = document.createElement("div");
    box.className = "banner banner-failure";
    box.setAttribute("role", "alert");
    const label = document.createElement("span");
    label.className = "banner-label";
    label.textContent = "failed";
    const words = document.createElement("span");
    // textContent, never innerHTML: this string can carry a server's own words.
    words.textContent = text;
    box.append(label, words);
    return box;
  }

  function showFailure(text, origin) {
    // The banner slot lives under the header, which is BEHIND an open dialog. A 5xx
    // during add-user therefore explained itself where the operator was not looking.
    // So a failure raised from inside a dialog is stated inside that dialog too —
    // both, not either: the banner is what remains once the dialog is closed.
    const dialog = origin && origin.closest ? origin.closest(".dialog") : null;
    if (dialog) {
      clearDialogFailure();
      const inside = failure(text);
      inside.dataset.dialogFailure = "true";
      const actions = dialog.querySelector(".dialog-actions");
      if (actions) actions.before(inside);
      else dialog.append(inside);
    }
    const host = slot("banner-slot");
    if (host) host.replaceChildren(failure(text));
  }

  function clearDialogFailure() {
    const host = slot("dialog-slot");
    if (!host) return;
    for (const stale of host.querySelectorAll("[data-dialog-failure]")) stale.remove();
  }

  function clearBanner() {
    const host = slot("banner-slot");
    if (host) host.replaceChildren();
    clearDialogFailure();
  }

  // --- copy ------------------------------------------------------------------

  async function copyFrom(button) {
    const source = document.getElementById(button.dataset.copyFrom);
    if (!source) return;
    const text = source.textContent.trim();
    let copied = false;
    try {
      // Only available in a secure context. The console is reached over plain HTTP
      // at an address behind the management tunnel, where it is not — hence the
      // fallback below rather than a promise nobody catches.
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch {
      copied = selectAndCopy(source);
    }
    button.dispatchEvent(new CustomEvent("hashi:copied", {
      bubbles: true,
      detail: { copied },
    }));
  }

  function selectAndCopy(node) {
    const range = document.createRange();
    range.selectNodeContents(node);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    try {
      return document.execCommand("copy");
    } catch {
      return false;
    }
  }

  function flash(message) {
    const host = slot("toast-slot");
    if (!host) return;
    const toast = document.createElement("div");
    toast.className = "toast blueprint";
    toast.setAttribute("role", "status");
    toast.textContent = message;
    for (const corner of ["tl", "tr", "bl", "br"]) {
      const mark = document.createElement("i");
      mark.className = "corner " + corner;
      toast.append(mark);
    }
    host.replaceChildren(toast);
    armToast();
  }

  // --- wiring ----------------------------------------------------------------

  document.addEventListener("click", (event) => {
    const backdrop = event.target.closest(".dialog-backdrop");
    // A click that landed on the backdrop itself, not inside the dialog — which is
    // the design's "click-outside closes; content click stops propagation".
    if (backdrop && !event.target.closest(".dialog")) {
      closeDialog();
      return;
    }
    if (event.target.closest("[data-close-dialog]")) {
      event.preventDefault();
      closeDialog();
      return;
    }
    const copyButton = event.target.closest("[data-copy-from]");
    if (copyButton) {
      event.preventDefault();
      copyFrom(copyButton);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeDialog();
  });

  document.addEventListener("hashi:copied", (event) => {
    flash(event.detail.copied
      ? "link copied"
      : "this browser would not copy — the link is selected, press copy yourself");
  });

  // A screen change closes any open dialog (design/README.md: "Modals close on
  // route change") and clears a stale failure banner.
  document.body.addEventListener("htmx:beforeRequest", (event) => {
    if (event.detail.elt.closest(".sidenav-list")) {
      closeDialog();
      clearBanner();
      return;
    }
    // A retry from inside a dialog drops the last failure it printed there, so the
    // operator never reads a stale explanation of a request that is still in flight.
    if (event.detail.elt.closest(".dialog")) clearDialogFailure();
  });

  // Observed rather than driven off an htmx event, deliberately. Both slots are
  // filled by OUT-OF-BAND swaps as well as by ordinary ones, and which event htmx
  // fires for an oob swap is a detail of its version — a MutationObserver is true
  // for every route into these two elements, including one written by this file.
  function watch(className, onFilled) {
    const host = slot(className);
    if (!host) return;
    new MutationObserver(() => onFilled(host)).observe(host, { childList: true });
  }

  watch("toast-slot", armToast);
  watch("dialog-slot", (host) => {
    const dialog = host.querySelector(".dialog");
    if (!dialog) return;
    const first = dialog.querySelector("input, textarea, select, button");
    if (first) first.focus();
  });

  // A form that renders one group of fields per choice, and shows the chosen one.
  // Generic on purpose: the select says which group it drives with
  // `data-transport-select`, each group names the value it belongs to with
  // `data-transport-group`, and nothing here knows what the values are. Presentation
  // ONLY — the server filters the submitted fields to the chosen transport's own
  // list, so a browser with this script dead still establishes the right hop.
  document.body.addEventListener("change", (event) => {
    const select = event.target.closest("[data-transport-select]");
    if (!select) return;
    const form = select.closest("form");
    if (!form) return;
    for (const group of form.querySelectorAll("[data-transport-group]")) {
      group.hidden = group.dataset.transportGroup !== select.value;
    }
  });

  // A refused form. htmx does not swap a non-2xx response by default, which would
  // leave a field-level validation message unrendered — so exactly one status is
  // allowed through, and it is marked "not an error" so the failure banner below
  // does not also fire on a mistyped nickname. Widening this list would turn every
  // server error into a swap, which is the reason it is a list of one.
  document.body.addEventListener("htmx:beforeSwap", (event) => {
    if (event.detail.xhr.status === 422) {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });

  // A request that never came back, or came back as a server error. HTMX swaps
  // nothing in either case, so without this the operator presses a button and the
  // panel simply does not move.
  // `event.detail.elt` is the element whose request failed — the form inside the
  // add-user dialog, say — which is how showFailure knows whether a dialog is in
  // front of the banner.
  const failed = (message) => (event) => showFailure(message, event.detail.elt);
  document.body.addEventListener("htmx:sendError", failed(
    "the panel could not reach the control plane. Nothing was changed — check that " +
    "the service is running, then try again."
  ));
  document.body.addEventListener("htmx:timeout", failed(
    "the control plane did not answer in time. It may still be finishing the " +
    "action — reload before trying it again."
  ));
  document.body.addEventListener("htmx:responseError", (event) => {
    const code = event.detail.xhr.status;
    showFailure(
      `the control plane refused that request (${code}). Nothing was changed. ` +
      "Reload the page; if it happens again, the container's log has the reason.",
      event.detail.elt
    );
  });
  // Any successful exchange clears a banner left over from an earlier failure.
  document.body.addEventListener("htmx:afterRequest", (event) => {
    if (event.detail.successful) clearBanner();
  });
})();
