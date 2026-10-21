/* Read-only current-task links. No network/storage/form writes or approvals. */
(function () {
  'use strict';
  function update(doc, jobId) {
    const valid = typeof jobId === 'string' && /^[a-f0-9]{32}$/.test(jobId);
    const href = valid ? '/studio?job=' + encodeURIComponent(jobId) : '/studio';
    doc.querySelectorAll('[data-task-studio-link]').forEach(link => {
      link.href = href;
      if (link.hasAttribute('data-task-required')) link.hidden = !valid;
    });
  }
  function mount(doc, getJobId) {
    const refresh = () => update(doc, getJobId());
    doc.addEventListener('workflow-render', refresh);
    refresh();
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {update, mount};
  if (typeof document !== 'undefined') {
    // app.js is a classic script; job is its existing lexical state, not a URL guess.
    mount(document, () => typeof job === 'undefined' ? null : job?.id);
  }
})();
