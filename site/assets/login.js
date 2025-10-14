async function sendLoginLink() {
  const email = document.getElementById("email").value;
  const msg = document.getElementById("message");
  msg.textContent = "";

  const res = await fetch("/api/login-magic-link", {
    method: "POST",
    headers: {
      "Authorization": "Bearer " + EDGE_FUNCTION_TOKEN,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ email, redirect_to: APP_URL })
  });

  if (res.ok) {
    msg.textContent = "Magic link wysłany! Sprawdź skrzynkę e-mail.";
  } else {
    const e = await res.text();
    msg.textContent = "Błąd: " + e;
  }
}
