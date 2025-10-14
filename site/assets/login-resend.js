(function(){
  const EDGE_URL = "/api/login-magic-link";
  const APP_URL  = "http://51.21.152.197:8501";

  const email = document.getElementById("email_login");
  const btn   = document.getElementById("send_login");
  const msg   = document.getElementById("msg_login");

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
        const ct = res.headers.get("content-type") || "";
        let t = await (ct.includes("application/json") ? res.json() : res.text());
        t = (typeof t === "string") ? t : (t?.error || JSON.stringify(t));
        setMsg("Błąd (login): " + t, "err");
        return;
      }
      setMsg("Wysłano. Sprawdź skrzynkę (login).", "ok");
      if (email) email.value = "";
    } catch (err) {
      setMsg("Błąd sieci: " + (err?.message || err), "err");
    }
  });
})();
