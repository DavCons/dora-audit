# app/app.py
# -*- coding: utf-8 -*-

import os
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st
from supabase import create_client, Client

# =============================================================================
#  UI: CSS + lekkie komponenty w stylu /site (ui_topbar, ui_header, ui_card)
# =============================================================================

def _inject_global_css():
    css_path = Path(__file__).with_name("assets") / "styles.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>",
                    unsafe_allow_html=True)

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
    st.markdown(f"""<a class="{cls}" href="{href}">{label}</a>""",
                unsafe_allow_html=True)

# =============================================================================
#  Hash → Query bridge (obsługa magic-linka z fragmentem #)
# =============================================================================
st.markdown("""
<script>
(function(){
  try{
    var h = window.location.hash || "";
    if (h && h.indexOf("access_token=") !== -1){
      var params = new URLSearchParams(h.substring(1));
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

# =============================================================================
#  Konfiguracja
# =============================================================================

SUPABASE_URL      = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
APP_BASE_URL      = os.getenv("APP_BASE_URL", "http://localhost:8501").strip()
SITE_BASE_URL     = os.getenv("SITE_BASE_URL", "http://localhost:8080").strip()

SURVEY_NAME = "DORA Audit"   # nazwa produktu/ankiety (1 wpis w 'surveys')

@st.cache_resource(show_spinner=False)
def supa() -> Client:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError("Brak SUPABASE_URL / SUPABASE_ANON_KEY w środowisku.")
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# =============================================================================
#  Query params helpers
# =============================================================================
def _get_query_params_dict() -> dict:
    try:
        # Streamlit 1.33+
        return dict(st.query_params)
    except Exception:
        # starsze API
        return st.experimental_get_query_params()

def _first(qp: dict, key: str):
    v = qp.get(key)
    if isinstance(v, list):
        return v[0] if v else None
    return v

def _clear_query_params():
    try:
        st.query_params.clear()
    except Exception:
        st.experimental_set_query_params()

# =============================================================================
#  Autoryzacja: magic-link (PKCE + tokeny) z obsługą hash→query
# =============================================================================
def require_auth_magic_link() -> bool:
    client = supa()
    qp = _get_query_params_dict()

    # a) PKCE: ?code=
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

    # b) Tokeny z mostka: ?access_token=&refresh_token=
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
            pass

    # c) Sesja z pamięci
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

    # d) Brak sesji — pokaż kartę z linkiem do /site
    ui_card(
        "🔐 Logowanie wymagane",
        "<p class='muted'>Użyj przycisku na stronie Checkout & FAQ, aby wysłać sobie magic-link.</p>",
        f"<a class='btn' href='{SITE_BASE_URL}/DORA_Checkout_and_FAQ.html'>➡️ Przejdź do: Checkout & FAQ</a>"
    )
    return False

# =============================================================================
#  Whitelist / role
# =============================================================================
def _get_current_user_email(client: Client) -> Optional[str]:
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
        res = (client.table("allowed_emails")
               .select("email")
               .eq("email", email)
               .maybe_single()
               .execute())
        row = getattr(res, "data", None) or (isinstance(res, dict) and res.get("data"))
        if not row:
            ui_card(
                "⛔ Brak dostępu",
                f"<p class='muted'>Adres <b>{email}</b> nie znajduje się na liście dozwolonych użytkowników.</p>",
                f"<a class='btn' href='{SITE_BASE_URL}/DORA_Checkout_and_FAQ.html'>➡️ Przejdź do: Checkout & FAQ</a>"
            )
            st.stop()
    except Exception as e:
        st.error(f"Błąd podczas weryfikacji dostępu: {e}")
        st.stop()

def is_admin(client: Client, email: str) -> bool:
    if not email:
        return False
    try:
        res = (client.table("allowed_emails")
               .select("is_admin")
               .eq("email", email)
               .maybe_single()
               .execute())
        row = getattr(res, "data", None) or (isinstance(res, dict) and res.get("data"))
        return bool(row and row.get("is_admin"))
    except Exception:
        return False

# =============================================================================
#  Ankiety / wersje (survey + survey_versions)
# =============================================================================
def _get_or_create_survey(client: Client) -> Dict[str, Any]:
    res = client.from_("surveys").select("*").eq("name", SURVEY_NAME).limit(1).execute()
    if res.data:
        return res.data[0]
    ins = client.from_("surveys").insert({"name": SURVEY_NAME}).select("*").single().execute()
    if ins.error:
        # wyścig – spróbuj jeszcze raz odczytać
        res2 = client.from_("surveys").select("*").eq("name", SURVEY_NAME).limit(1).execute()
        if not res2.data:
            raise RuntimeError(f"Nie udało się utworzyć ani odczytać survey: {ins.error}")
        return res2.data[0]
    return ins.data

def _next_version_number(client: Client, survey_id: str) -> int:
    res = (client.from_("survey_versions")
           .select("version")
           .eq("survey_id", survey_id)
           .order("version", desc=True)
           .limit(1)
           .execute())
    if res.data:
        return int(res.data[0]["version"]) + 1
    return 1

def _set_active_version(client: Client, survey_id: str, version_id: str) -> None:
    # wyłącz inne
    upd1 = client.from_("survey_versions").update({"is_active": False}).eq("survey_id", survey_id).execute()
    if upd1.error:
        raise RuntimeError(f"Deactive others: {upd1.error}")
    # włącz wskazaną
    upd2 = client.from_("survey_versions").update({"is_active": True}).eq("id", version_id).execute()
    if upd2.error:
        raise RuntimeError(f"Activate chosen: {upd2.error}")

def _save_new_version(
    client: Client,
    survey_id: str,
    content: Dict[str, Any],
    threshold_green: int,
    threshold_amber: int,
    created_by: str,
    set_active: bool,
) -> Dict[str, Any]:
    version_no = _next_version_number(client, survey_id)
    ins = (client.from_("survey_versions").insert({
        "survey_id":       survey_id,
        "version":         version_no,
        "content":         content,
        "threshold_green": int(threshold_green),
        "threshold_amber": int(threshold_amber),
        "created_by":      created_by,
        "is_active":       False,
    }).select("*").single().execute())
    if ins.error:
        raise RuntimeError(f"Insert survey_versions: {ins.error}")
    ver = ins.data
    if set_active:
        _set_active_version(client, survey_id, ver["id"])
        ver["is_active"] = True
    return ver

def _load_active_version(client: Client) -> Optional[Dict[str, Any]]:
    survey = _get_or_create_survey(client)
    res = (client.from_("survey_versions")
           .select("*")
           .eq("survey_id", survey["id"])
           .eq("is_active", True)
           .limit(1)
           .execute())
    if res.data:
        return res.data[0]
    return None

def _list_versions(client: Client) -> List[Dict[str, Any]]:
    survey = _get_or_create_survey(client)
    res = (client.from_("survey_versions")
           .select("id, version, created_at, threshold_green, threshold_amber, is_active, created_by")
           .eq("survey_id", survey["id"])
           .order("version", desc=True)
           .execute())
    if res.error:
        raise RuntimeError(res.error.message)
    return res.data or []

# =============================================================================
#  Parsowanie uploadu (CSV / JSON)
# =============================================================================
def _parse_uploaded_file(upl) -> Dict[str, Any]:
    """
    Zwraca dict (content) gotowy do zapisania w JSONB.
    CSV -> records; JSON -> dowolny obiekt/array.
    """
    if upl is None:
        raise ValueError("Nie wybrano pliku.")
    name = upl.name.lower()
    raw = upl.read()
    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(raw))
        return {"type": "csv", "records": json.loads(df.to_json(orient="records"))}
    else:
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            text = raw.decode("utf-8")
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
            data = rows
        return {"type": "json", "data": data}

# =============================================================================
#  Widoki: User / Admin
# =============================================================================
def render_login_required():
    ui_card(
        "🔐 Logowanie wymagane",
        "<p class='muted'>Użyj przycisku na stronie Checkout & FAQ, aby wysłać sobie magic-link.</p>",
        f"<a class='btn' href='{SITE_BASE_URL}/DORA_Checkout_and_FAQ.html'>➡️ Przejdź do: Checkout & FAQ</a>"
    )

def render_user_panel(client: Client, email: str):
    ui_header("📋 Moje ankiety", f"Zalogowano jako: {email}")
    active = _load_active_version(client)
    if active:
        ui_card(
            f"Aktywna wersja: v{active['version']}",
            f"<div class='muted'>Progi: GREEN {active['threshold_green']}% • AMBER {active['threshold_amber']}% "
            f"• utworzono {active['created_at']}</div>"
        )
        c1, c2 = st.columns(2)
        with c1:
            st.button("➕ Rozpocznij nową ankietę", type="primary", use_container_width=True)
        with c2:
            st.button("⤴️ Wróć do ostatniej ankiety", use_container_width=True)
    else:
        ui_card("Brak aktywnej wersji ankiety", "<p class='muted'>Skontaktuj się z administratorem.</p>")

def render_versions_admin_block(client: Client):
    st.subheader("Wersje ankiety")
    try:
        rows = _list_versions(client)
    except Exception as e:
        st.error(f"Nie udało się pobrać wersji: {e}")
        return
    if not rows:
        st.info("Brak zapisanych wersji ankiety.")
        return

    import pandas as _pd
    df = _pd.DataFrame(rows)
    df = df.rename(columns={
        "version": "ver",
        "created_at": "utworzono",
        "threshold_green": "GREEN",
        "threshold_amber": "AMBER",
        "is_active": "aktywna",
        "created_by": "autor"
    })[["ver", "GREEN", "AMBER", "aktywna", "autor", "utworzono", "id"]]
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.caption("Akcje:")
    cols = st.columns(min(4, len(rows)))
    survey = _get_or_create_survey(client)
    for idx, v in enumerate(rows):
        with cols[idx % len(cols)]:
            label = f"Ustaw aktywną: v{v['ver'] if 'ver' in v else v['version']}"
            disabled = bool(v.get("is_active"))
            if st.button(label, key=f"set_active_{v['id']}", disabled=disabled):
                try:
                    _set_active_version(client, survey_id=survey["id"], version_id=v["id"])
                    st.success(f"Aktywowano wersję v{v.get('ver', v['version'])}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Nie udało się aktywować wersji: {e}")

def render_admin_upload_block(client: Client, current_email: str):
    st.subheader("Wgraj nową ankietę")
    st.caption("Załaduj plik CSV/JSON i ustaw progi „green/amber”.")

    upl = st.file_uploader("Plik ankiety", type=["csv", "json"])
    col_g, col_a, col_chk = st.columns([1,1,1])
    with col_g:
        green = st.number_input("Próg GREEN (%)", min_value=0, max_value=100, value=80, step=1)
    with col_a:
        amber = st.number_input("Próg AMBER (%)", min_value=0, max_value=100, value=60, step=1)
    with col_chk:
        set_active = st.checkbox("Ustaw jako aktywną", value=True)

    if st.button("💾 Zapisz nową wersję", type="primary"):
        if not upl:
            st.error("Nie wybrano pliku.")
            return
        try:
            survey = _get_or_create_survey(client)
            parsed: Dict[str, Any] = _parse_uploaded_file(upl)
            ver = _save_new_version(
                client,
                survey_id=survey["id"],
                content=parsed,
                threshold_green=int(green),
                threshold_amber=int(amber),
                created_by=current_email,
                set_active=set_active,
            )
            st.success(f"Zapisano wersję v{ver['version']} (active={ver['is_active']}).")
        except Exception as e:
            st.error(f"❌ Nie udało się zapisać nowej wersji: {e}")

def render_admin_whitelist_block(client: Client):
    st.subheader("Whitelist / Administratorzy")
    email_input = st.text_input("Dodaj adres e-mail", placeholder="user@firma.com")
    c1, c2, c3 = st.columns([1,1,1])
    with c1:
        if st.button("Dodaj do whitelisty (user)", type="secondary", use_container_width=True):
            if not email_input:
                st.error("Podaj e-mail.")
            else:
                up = (client.from_("allowed_emails")
                      .upsert({"email": email_input.strip().lower(),
                               "source": "admin",
                               "is_admin": False}, on_conflict="email")
                      .execute())
                if up.error:
                    st.error(up.error.message)
                else:
                    st.success(f"Dodano/zaktualizowano {email_input} jako użytkownika.")
    with c2:
        if st.button("Dodaj jako administratora", type="primary", use_container_width=True):
            if not email_input:
                st.error("Podaj e-mail.")
            else:
                up = (client.from_("allowed_emails")
                      .upsert({"email": email_input.strip().lower(),
                               "source": "admin",
                               "is_admin": True}, on_conflict="email")
                      .execute())
                if up.error:
                    st.error(up.error.message)
                else:
                    st.success(f"{email_input} posiada uprawnienia administratora.")
    with c3:
        if st.button("Usuń uprawnienia admin", use_container_width=True):
            if not email_input:
                st.error("Podaj e-mail.")
            else:
                up = (client.from_("allowed_emails")
                      .upsert({"email": email_input.strip().lower(),
                               "is_admin": False}, on_conflict="email")
                      .execute())
                if up.error:
                    st.error(up.error.message)
                else:
                    st.success(f"Usunięto uprawnienia admin dla {email_input}.")

    st.divider()
    lst = (client.from_("allowed_emails")
           .select("email, created_at, source, is_admin")
           .order("email")
           .execute())
    if lst.error:
        st.error(lst.error.message)
    else:
        import pandas as _pd
        df = _pd.DataFrame(lst.data or [])
        st.dataframe(df, use_container_width=True, hide_index=True)

def render_admin_panel(client: Client, email: str):
    ui_header("👑 Panel administracyjny", f"Zalogowano jako: {email}")
    render_admin_upload_block(client, email)

    st.divider()
    st.subheader("Aktywna wersja")
    try:
        active = _load_active_version(client)
        if active:
            st.success(f"v{active['version']} | green={active['threshold_green']} | amber={active['threshold_amber']}")
        else:
            st.warning("Brak aktywnej wersji.")
    except Exception as e:
        st.error(f"Nie udało się pobrać wersji: {e}")

    st.divider()
    st.caption("Poniżej znajdziesz wszystkie zapisane wersje ankiety. Kliknij przycisk, aby ustawić wersję aktywną.")
    render_versions_admin_block(client)

    st.divider()
    render_admin_whitelist_block(client)

# =============================================================================
#  Sidebar: Sesja / Wylogowanie
# =============================================================================
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

# =============================================================================
#  App start
# =============================================================================

st.set_page_config(page_title="DORA Audit — MVP", layout="wide")
_inject_global_css()
ui_topbar(SITE_BASE_URL)

if not require_auth_magic_link():
    st.stop()

client = supa()
_enforce_allowed_email(client)

current_email = _get_current_user_email(client) or ""
user_is_admin = is_admin(client, current_email)

ui_header("DORA Audit — MVP")

# Prosta nawigacja
page = st.sidebar.radio(
    "Nawigacja",
    ["Moje ankiety"] + (["Panel administracyjny"] if user_is_admin else [])
)

if page == "Panel administracyjny":
    render_admin_panel(client, current_email)
else:
    render_user_panel(client, current_email)

session_bar(client)

