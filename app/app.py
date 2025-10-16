# app/app.py
import os
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components

from supabase import create_client
from supabase.client import Client  # typ dla adnotacji

# ========= Konfiguracja =========
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8501").strip()
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "http://localhost:8080").strip()

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
    st.markdown(f"""
    <div style="background:#17171b;border:1px solid #26262b;border-radius:14px;padding:22px 18px;margin:18px 0">
      <h2 style="margin:0 0 12px 0">🔐 Logowanie wymagane</h2>
      <p style="color:#a7a7ad;margin:0 0 10px 0">
        Użyj przycisku na stronie Checkout & FAQ, aby wysłać sobie magic-link.
      </p>
      <p style="margin:0">
        <a href="{SITE_BASE_URL}/DORA_Checkout_and_FAQ.html" style="color:#9b8cf0;text-decoration:none">
          ➡️ Przejdź do: Checkout & FAQ
        </a>
      </p>
    </div>
    """, unsafe_allow_html=True)
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
def render_admin_panel(client: Client, email: str):
    st.subheader("👑 Panel administracyjny")
    st.caption(f"Zalogowano jako: {email}")

    with st.expander("Wgraj nową ankietę (CSV/JSON)", expanded=True):
        upl = st.file_uploader("Plik ankiety", type=["csv", "json"])
        green = st.number_input("Próg GREEN (%)", 0, 100, 80)
        amber = st.number_input("Próg AMBER (%)", 0, 100, 60)
        if st.button("Zapisz konfigurację", type="primary", use_container_width=True):
            # TODO: zapisz do supabase storage/tables wg Twojego modelu
            st.success("Konfiguracja zapisana (placeholder).")

    st.divider()

    with st.expander("Lista dozwolonych adresów", expanded=False):
        try:
            res = client.table("allowed_emails").select("*").order("email").execute()
            rows = getattr(res, "data", None) or (isinstance(res, dict) and res.get("data")) or []
            st.dataframe(rows, use_container_width=True)
        except Exception as e:
            st.error(f"Nie udało się pobrać listy: {e}")


def render_user_panel(client: Client, email: str):
    st.subheader("📋 Moje ankiety")
    st.caption(f"Zalogowano jako: {email}")

    # TODO: pobieranie statusów z tabeli np. surveys/submissions
    # Na razie placeholder:
    st.info("Tu pojawi się lista Twoich ankiet i status realizacji (placeholder).")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("➕ Rozpocznij nową ankietę", type="primary", use_container_width=True):
            st.success("Start nowej ankiety (placeholder).")
    with col2:
        if st.button("🔄 Wróć do ostatniej ankiety", use_container_width=True):
            st.info("Wczytanie ostatniej ankiety (placeholder).")


# ========= Pasek sesji / logout =========
def session_bar(client: Client):
    st.sidebar.markdown("### 🔐 Session")
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
st.title("DORA Audit — MVP")
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
