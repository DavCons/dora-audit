(function(){
  const EDGE_URL = "/api/checkout-magic-link";
  const APP_URL  = "http://51.21.152.197:8501";

  const email = document.getElementById("email_checkout");
  const btn   = document.getElementById("send_checkout");
  const msg   = document.getElementById("msg_checkout");

  function setMsg(t, cls){ msg.textContent = t || ""; msg.className = "msg" + (cls ? (" " + cls) : ""); }

  btn?.addEventListener("click", async ()=>{
    setMsg("");
    const e = (email?.value || "").trim();
    if(!e){ setMsg("Podaj e-mail.", "err"); return; }
    try{
      const res = await fetch(EDGE_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: e, redirect_to: APP_URL })
      });
      if(!res.ok){
        let text;
        try { text = await res.text(); } catch { text = String(res.status); }
        setMsg("Błąd (checkout): " + text, "err");
        return;
      }
      setMsg("Wysłano. Sprawdź skrzynkę (checkout).", "ok");
      if (email) email.value = "";
    } catch (err) {
      setMsg("Błąd sieci: " + (err?.message || err), "err");
    }
  });
})();
