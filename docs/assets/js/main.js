document.addEventListener('DOMContentLoaded', () => {
  // Tabs
  const tabBtns = document.querySelectorAll('.tab-btn');
  const panels = document.querySelectorAll('.tab-panel');
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      panels.forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(btn.dataset.tab).classList.add('active');
    });
  });

  // Copy BibTeX
  const copyBtn = document.querySelector('.copy-btn');
  if (copyBtn) {
    copyBtn.addEventListener('click', () => {
      const text = document.querySelector('.cite-box pre').innerText;
      navigator.clipboard.writeText(text).then(() => {
        const old = copyBtn.textContent;
        copyBtn.textContent = 'Copied!';
        setTimeout(() => (copyBtn.textContent = old), 1600);
      });
    });
  }

  // Animate bar widths on scroll into view
  const bars = document.querySelectorAll('.bar-fill');
  const obs = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        const el = e.target;
        el.style.width = el.dataset.width;
        obs.unobserve(el);
      }
    });
  }, { threshold: 0.3 });
  bars.forEach(b => {
    b.dataset.width = b.style.width;
    b.style.width = '0%';
    obs.observe(b);
  });
});
