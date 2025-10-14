async function sendMagicLink() {
  const email = document.getElementById("email").value;
  const msg = document.getElementById("message");
  msg.textContent = "";

  const res = await fetch("/api/checkout-magic-link", {
    method: "POST",
    headers: {
      "Authorization": "Bearer " + EDGE_FUNCTION_TOKEN,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ email, redirect_to: APP_URL })
  });

  if (res.ok) {
    msg.textContent = "Magic link został wysłany! Sprawdź skrzynkę e-mail.";
  } else {
    const e = await res.text();
    msg.textContent = "Błąd: " + e;
  }
}
