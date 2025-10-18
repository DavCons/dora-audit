# app/app.py
import os
from datetime import datetime
import streamlit as st

# --- na samej górze (po importach os/datetime/streamlit) ---
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

# === Wstrzyknięcie globalnego CSS ===
def _inject_global_css():
    css_path = Path(__file__).with_name("assets") / "styles.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

# === Proste komponenty UI (spójne z /site) ===
def ui_topbar(site_base_url: str):
    st.markdown(f"""
    <div class="topbar">
      <div style="display:flex;gap:10px;align-items:center;">
        <span class="badge">DORA Audit</span>
      </div>
      <div class="links">
        <a href="{site_base_url}/DORA_Checkout_and_FAQ.html">Checkout & FAQ</a>
      </div>
    </div>
    """, unsafe_allow_html=True)

def ui_header(title: str, subtitle: str = ""):
    st.markdown(f"""
    <div class="section">
      <div class="page-title">{title}</div>
      {"<div class='muted'>" + subtitle + "</div>" if subtitle else ""}
    </div>
    """, unsafe_allow_html=True)

def ui_card(title: str, body_html: str = "", footer_html: str = ""):
    st.markdown(f"""
    <div class="card">
      {"<h3>"+title+"</h3>" if title else ""}
      {body_html}
      {("<div style='margin-top:10px'>" + footer_html + "</div>") if footer_html else ""}
    </div>
    """, unsafe_allow_html=True)

def ui_button(label: str, href: str = "#", kind: str = "primary"):
    cls = "btn" if kind == "primary" else "btn secondary"
    st.markdown(f"""<a class="{cls}" href="{href}">{label}</a>""", unsafe_allow_html=True)

# --- HASH → QUERY bridge (dla linków z #access_token) ---
st.markdown("""
<script>
(function(){
  try{
    var h = window.location.hash || "";
    if (h && h.indexOf("access_token=") !== -1){
      var params = new URLSearchParams(h.substring(1));
      // zabezpieczenie przed pętlą:
      if (!params.get("from_hash")) {
        params.set("from_hash","1");
        var target = window.location.origin + window.location.pathname + "?" + params.toString();
        window.location.replace(target);
      }
    }
  }catch(e){ console.log("hash→query bridge error", e); }
})();
</script>
""", unsafe_allow_html=True)

import streamlit.components.v1 as components

from supabase import create_client
from supabase.client import Client  # typ dla adnotacji

# ========= Konfiguracja =========
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8501").strip()
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "http://localhost:8080").strip()

DEBUG_LOGIN = False

@st.cache_resource(show_spinner=False)
def supa() -> Client:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError("Brak SUPABASE_URL / SUPABASE_ANON_KEY w środowisku.")
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# ========= Helpery do query params (kompatybilność wersji Streamlit) =========
def _get_query_params_dict() -> dict:
    """Zwraca query params jako zwykły dict[str, list[str]] (nowe i stare Streamlity)."""
    try:
        return dict(st.query_params)
    except Exception:
        return st.experimental_get_query_params()

def _first(qp: dict, key: str):
    """Zwróć pierwszy element z listy lub stringa jeśli klucz istnieje."""
    v = qp.get(key)
    if isinstance(v, list):
        return v[0] if v else None
    return v

def _clear_query_params():
    try:
        st.query_params.clear()
    except Exception:
        st.experimental_set_query_params()

# ========= Autoryzacja: magic-link / code / tokens =========
def require_auth_magic_link() -> bool:
    """
    Zwraca True gdy użytkownik jest zalogowany (auth.get_user() działa),
    w przeciwnym razie renderuje kartę z linkiem do /site i zwraca False.
    """
    client = supa()

    qp = _get_query_params_dict()

    if DEBUG_LOGIN:
        st.info(f"QP (server): {qp}")
        st.caption(f"Session keys: {list(st.session_state.keys())}")

    # 1) Ścieżka PKCE z ?code=
    code = _first(qp, "code")
    if code:
        with st.spinner("Signing you in…"):
            try:
                data = client.auth.exchange_code_for_session({"auth_code": code})
                session = getattr(data, "session", None) or (isinstance(data, dict) and data.get("session"))
                access  = getattr(session, "access_token", None) or (session and session.get("access_token"))
                refresh = getattr(session, "refresh_token", None) or (session and session.get("refresh_token"))
                if access:
                    try:
                        client.auth.set_session(access, refresh)
                    except Exception:
                        client.auth.set_auth(access)
                    st.session_state["access_token"] = access
                    if refresh:
                        st.session_state["refresh_token"] = refresh
                    _clear_query_params()
                    st.rerun()
            except Exception:
                st.error("Nie udało się wymienić code → session.")
                _clear_query_params()
                st.stop()

    # 2) Ścieżka z ?access_token=&refresh_token=
    access = _first(qp, "access_token")
    refresh = _first(qp, "refresh_token")
    if access:
        try:
            if refresh:
                client.auth.set_session(access, refresh)
            else:
                try:
                    client.auth.set_session(access, None)
                except Exception:
                    client.auth.set_auth(access)
            st.session_state["access_token"] = access
            if refresh:
                st.session_state["refresh_token"] = refresh
            _clear_query_params()
            st.rerun()
        except Exception:
            pass  # przejdź dalej

    # 3) Sesja z pamięci
    at = st.session_state.get("access_token")
    rt = st.session_state.get("refresh_token")
    if at:
        try:
            if rt:
                client.auth.set_session(at, rt)
            else:
                try:
                    client.auth.set_session(at, None)
                except Exception:
                    client.auth.set_auth(at)
            u = client.auth.get_user()
            if u:
                return True
        except Exception:
            st.session_state.pop("access_token", None)
            st.session_state.pop("refresh_token", None)

    # 4) Brak sesji → karta z linkiem do /site

    if DEBUG_LOGIN:
        try:
            u = supa().auth.get_user()
            st.caption(f"auth.get_user(): {u}")
        except Exception as e:
            st.caption(f"auth.get_user() error: {e}")

    ui_card(
        "🔐 Logowanie wymagane",
        "<p class='muted'>Użyj przycisku na stronie Checkout & FAQ, aby wysłać sobie magic-link.</p>",
        f"<a class='btn' href='{SITE_BASE_URL}/DORA_Checkout_and_FAQ.html'>➡️ Przejdź do: Checkout & FAQ</a>"
    )
    return False


# ========= Whitelist & role =========
def _get_current_user_email(client: Client) -> str | None:
    try:
        u = client.auth.get_user().user
        return getattr(u, "email", None)
    except Exception:
        return None

def _enforce_allowed_email(client: Client):
    email = _get_current_user_email(client)
    if not email:
        st.error("Nie udało się ustalić adresu e-mail użytkownika.")
        st.stop()
    try:
        res = client.table("allowed_emails").select("email").eq("email", email).maybe_single().execute()
        row = getattr(res, "data", None) or (isinstance(res, dict) and res.get("data"))
        if not row:
            st.warning(f"Adres {email} nie znajduje się na liście dozwolonych użytkowników.")
            st.markdown(f"""
            <div style="background:#17171b;border:1px solid #26262b;border-radius:14px;padding:22px 18px;margin:18px 0">
              <p style="color:#a7a7ad;">Aby uzyskać dostęp, poproś administratora o dopisanie Twojego adresu e-mail do whitelisty.</p>
              <p style="margin:0">
                <a href="{SITE_BASE_URL}/DORA_Checkout_and_FAQ.html" style="color:#9b8cf0;text-decoration:none">
                  ➡️ Przejdź do: Checkout & FAQ
                </a>
              </p>
            </div>
            """, unsafe_allow_html=True)
            st.stop()
    except Exception as e:
        st.error(f"Błąd podczas weryfikacji dostępu: {e}")
        st.stop()

def is_admin(client: Client, email: str) -> bool:
    if not email:
        return False
    try:
        res = client.table("allowed_emails").select("is_admin").eq("email", email).maybe_single().execute()
        row = getattr(res, "data", None) or (isinstance(res, dict) and res.get("data"))
        return bool(row and row.get("is_admin"))
    except Exception:
        return False


# ========= Widoki =========
def _parse_uploaded_file(upl) -> Dict[str, Any]:
    """
    Zamienia CSV/JSON na standardowy JSON “ankiety”.
    Przyjmijmy prosty format: lista pytań [{id, text, ...}].
    """
    if upl is None:
        return {}
    name = upl.name.lower()
    if name.endswith(".json"):
        return json.load(upl)
    elif name.endswith(".csv"):
        df = pd.read_csv(upl)
        return json.loads(df.to_json(orient="records"))
    else:
        raise ValueError("Obsługiwane typy: CSV lub JSON")

def render_admin_panel(client, email: str):
    ui_header("👑 Panel administracyjny", f"Zalogowano jako: {email}")

    # --- wgrywanie nowej wersji ---
    ui_card("Wgraj nową ankietę",
            "<div class='muted'>Załaduj plik CSV/JSON oraz ustaw progi „green/amber”.</div>")

    upl = st.file_uploader("Plik ankiety", type=["csv", "json"], label_visibility="visible")
    colg, cola, colc = st.columns([1,1,1])
    with colg:
        green = st.number_input("Próg GREEN (%)", min_value=0, max_value=100, value=80, step=1,
                                label_visibility="visible")
    with cola:
        amber = st.number_input("Próg AMBER (%)", min_value=0, max_value=100, value=60, step=1,
                                label_visibility="visible")
    with colc:
        set_active_now = st.checkbox("Ustaw jako aktywną", value=False)

    if st.button("Zapisz nową wersję", type="primary"):
        try:
            content = _parse_uploaded_file(upl)
            if not content:
                st.error("Brak/niepoprawny plik.")
            else:
                survey_id = _get_or_create_survey(client)
                next_ver = _get_next_version(client, survey_id)
                thresholds = {"green": int(green), "amber": int(amber)}
                ins = (client.table("survey_versions").insert({
                        "survey_id": survey_id,
                        "version": next_ver,
                        "content": content,
                        "thresholds": thresholds,
                        "is_active": False,
                        "created_by": email,
                      })
                      .select("id")
                      .single()
                      .execute())
                ver_id = ins.data["id"]
                if set_active_now:
                    _activate_version(client, survey_id, ver_id)
                st.success(f"Zapisano wersję {next_ver}{' (aktywna)' if set_active_now else ''}.")
        except Exception as e:
            st.error(f"Nie udało się zapisać wersji: {e}")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # --- wybór aktywnej wersji ---
    ui_card("Aktywna wersja")
    try:
        survey_id = _get_or_create_survey(client)
        res = (client.table("survey_versions")
               .select("id, version, is_active, created_at, thresholds")
               .eq("survey_id", survey_id)
               .order("version", desc=True)
               .execute())
        rows = getattr(res, "data", None) or []
        if rows:
            labels = [f"v{r['version']}  {'(akty.)' if r['is_active'] else ''}  /  "
                      f"prog: G{r['thresholds'].get('green','?')} A{r['thresholds'].get('amber','?')}  "
                      f"/ {r['created_at']}" for r in rows]
            idx = st.selectbox("Wersje", options=list(range(len(rows))), format_func=lambda i: labels[i],
                               label_visibility="visible")
            if st.button("Ustaw wybraną wersję jako aktywną"):
                _activate_version(client, survey_id, rows[idx]["id"])
                st.success(f"Aktywowano wersję v{rows[idx]['version']}.")
                st.experimental_rerun()
        else:
            st.info("Brak wersji ankiety.")
    except Exception as e:
        st.error(f"Nie udało się pobrać wersji: {e}")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # --- zarządzanie whitelistą i adminami ---
    ui_card("Whitelist / Administratorzy")
    new_admin = st.text_input("Dodaj adres e-mail jako administratora", "", placeholder="user@firma.com",
                              label_visibility="visible")
    cols = st.columns([1,1])
    with cols[0]:
        if st.button("Dodaj do whitelisty (user)"):
            try:
                client.table("allowed_emails").upsert({
                    "email": new_admin.strip().lower(),
                    "is_admin": False,
                    "source": "admin_panel"
                }, on_conflict="email").execute()
                st.success("Dodano/zmodyfikowano w whitelist.")
            except Exception as e:
                st.error(f"Błąd whitelist: {e}")
    with cols[1]:
        if st.button("Dodaj jako administratora"):
            try:
                client.table("allowed_emails").upsert({
                    "email": new_admin.strip().lower(),
                    "is_admin": True,
                    "source": "admin_panel"
                }, on_conflict="email").execute()
                st.success("Dodano/zmodyfikowano administratora.")
            except Exception as e:
                st.error(f"Błąd admin: {e}")

    # podgląd listy
    try:
        tab = client.table("allowed_emails").select("email, created_at, source, is_admin").order("email").execute()
        st.dataframe(getattr(tab, "data", None) or [], use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Nie udało się pobrać listy: {e}")



def render_user_panel(client: Client, email: str):

    ui_header("📋 Moje ankiety", f"Zalogowano jako: {email}")
    active = _load_active_version(client)

    if active:
        thr = active["thresholds"]
        ui_card(
            f"Aktywna wersja ankiety: v{active['version']}",
            f"<div class='muted'>Progi: GREEN {thr.get('green')}% • AMBER {thr.get('amber')}%</div>"
        )
    else:
        st.warning("Brak aktywnej wersji ankiety. Skontaktuj się z administratorem.")

    # …dalej Twoje przyciski i lista “Moje ankiety”…
    ui_header("📋 Moje ankiety", f"Zalogowano jako: {email}")

    ui_card(
        "Status realizacji",
        "<p class='muted'>Tu pojawi się lista Twoich ankiet i status (placeholder).</p>"
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("➕ Rozpocznij nową ankietę", type="primary", use_container_width=True):
            st.success("Start nowej ankiety (placeholder).")
    with col2:
        if st.button("🔄 Wróć do ostatniej ankiety", use_container_width=True):
            st.info("Wczytanie ostatniej ankiety (placeholder).")


# ========= Pasek sesji / logout =========
def session_bar(client: Client):
    st.sidebar.markdown("#### 👤 Sesja", help="Informacje o zalogowanym użytkowniku")
    try:
        u = client.auth.get_user().user
        email = getattr(u, "email", "—")
        exp = getattr(u, "exp", None) or None
    except Exception:
        email, exp = "—", None

    st.sidebar.write("User:", email)
    if exp:
        try:
            dt = datetime.utcfromtimestamp(int(exp))
            st.sidebar.write("Expires:", f"{dt} UTC")
        except Exception:
            pass

    if st.sidebar.button("Sign out", use_container_width=True):
        try:
            client.auth.sign_out()
        finally:
            st.session_state.pop("access_token", None)
            st.session_state.pop("refresh_token", None)
            _clear_query_params()
            st.rerun()


# ========= GŁÓWNA LOGIKA (po definicjach!) =========
# Nagłówek strony
st.set_page_config(page_title="DORA Audit — MVP", layout="wide")

# po st.set_page_config()
_inject_global_css()
ui_topbar(SITE_BASE_URL)

# 1) Autoryzacja
if not require_auth_magic_link():
    st.stop()

# 2) Whitelist
client = supa()
_enforce_allowed_email(client)

# 3) Kto
current_email = _get_current_user_email(client) or ""
user_is_admin = is_admin(client, current_email)

# 4) Tytuł i nawigacja
ui_header("DORA Audit — MVP")

page = st.sidebar.radio(
    "Nawigacja",
    ["Moje ankiety"] + (["Panel administracyjny"] if user_is_admin else [])
)

# 5) Widok strony
if page == "Panel administracyjny":
    render_admin_panel(client, current_email)
else:
    render_user_panel(client, current_email)

# 6) Pasek sesji
session_bar(client)
