(() => {
  const load = () => {
  const container = document.getElementById('fragment');
  if (!container) return;
  fetch('/fragment', { credentials: 'same-origin', cache: 'no-store', redirect: 'error' })
    .then(response => {
      if (!response.ok) throw new Error('Transmission unavailable');
      return response.text();
    })
    .then(text => { container.textContent = text; })
    .catch(() => { container.textContent = ''; });
  };
  if (document.readyState === 'complete') load();
  else window.addEventListener('load', load, { once: true });
})();
