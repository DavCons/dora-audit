// Attach once DOM is ready
window.addEventListener('DOMContentLoaded', () => {
  const bind = (btnId, emailId, outId, endpoint) => {
    const btn   = document.getElementById(btnId);
    const email = document.getElementById(emailId);
    const out   = document.getElementById(outId);
    if (!btn || !email || !out) return;

    btn.addEventListener('click', async () => {
      const value = (email.value || '').trim();
      if (!value) { out.textContent = btn.dataset.lang === 'pl' ? 'Podaj adres e-mail.' : 'Please enter your email.'; return; }

      btn.disabled = true;
      out.textContent = btn.dataset.lang === 'pl' ? 'Wysyłanie…' : 'Sending…';
      try {
        const res = await fetch('/api/' + endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email: value,
            redirect_to: 'http://51.21.152.197:8501'
          })
        });
        const text = await res.text();
        out.textContent = res.ok
          ? (btn.dataset.lang === 'pl' ? 'OK — sprawdź skrzynkę ✉️' : 'OK — check your inbox ✉️')
          : `${btn.dataset.lang === 'pl' ? 'Błąd' : 'Error'} ${res.status}: ${text}`;
      } catch (e) {
        out.textContent = (btn.dataset.lang === 'pl' ? 'Błąd sieci: ' : 'Network error: ') + (e?.message || e);
      } finally {
        btn.disabled = false;
      }
    });
  };

  // PL
  bind('checkout-magic-link-btn-pl', 'checkout-email-pl', 'checkout-magic-link-out-pl', 'checkout-magic-link');
  bind('login-magic-link-btn-pl',    'login-email-pl',    'login-magic-link-out-pl',    'login-magic-link');

  // EN
  bind('checkout-magic-link-btn-en', 'checkout-email-en', 'checkout-magic-link-out-en', 'checkout-magic-link');
  bind('login-magic-link-btn-en',    'login-email-en',    'login-magic-link-out-en',    'login-magic-link');
});
