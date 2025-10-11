
import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="DORA Compliance - MVP", layout="wide")
st.title("DORA Audit — MVP")

import os
from supabase import create_client
import streamlit as st

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
APP_BASE_URL = os.getenv("APP_BASE_URL", "").strip()  # e.g., "http://localhost:8501" or "https://your.domain"

_supabase = None
def supa():
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_ANON_KEY:
            st.warning("Supabase auth not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY to enable magic-link login.")
            return None
        _supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _supabase

def require_auth_magic_link() -> bool:
    """
    Returns True if user is authenticated (session present), else renders login UI and returns False.
    Flow:
      1) User enters email -> we call supabase.auth.sign_in_with_otp to send a magic link.
      2) Supabase redirects back to APP_BASE_URL with ?code=... -> we exchange code for a session.
    """
    sb = supa()
    if sb is None:
        return True  # let app work without auth if not configured

    # 1) If we came back from Supabase with ?code=..., exchange it for a session
    try:
        q = st.query_params if hasattr(st, "query_params") else st.experimental_get_query_params()
        code_param = None
        if isinstance(q, dict):
            if hasattr(q, "get"):
                v = q.get("code")
                if isinstance(v, list):
                    code_param = v[0] if v else None
                elif isinstance(v, str):
                    code_param = v
        if code_param:
            try:
                sb.auth.exchange_code_for_session(code_param)
                st.session_state["auth_ok"] = True
                st.session_state["auth_source"] = "supabase"
            except Exception as e:
                st.error("Auth exchange failed. The link may be expired or misconfigured.")
    except Exception:
        pass

    # 2) If we have an active session, we're good
    try:
        sess = sb.auth.get_session()
        if sess and getattr(sess, "access_token", None):
            st.session_state["auth_ok"] = True
            st.session_state["auth_user"] = getattr(getattr(sess, "user", None), "email", None) or "user"
    except Exception:
        # Some client versions return dict-like
        try:
            sess = sb.auth.get_session()
            if isinstance(sess, dict) and sess.get("access_token"):
                st.session_state["auth_ok"] = True
                st.session_state["auth_user"] = (sess.get("user") or {}).get("email") or "user"
        except Exception:
            pass

    if st.session_state.get("auth_ok"):
        return True

    # 3) Render email form to send magic link
    st.title("🔐 Sign in — Magic link")
    with st.form("magic_link"):
        email = st.text_input("Your email", value="", autocomplete="email")
        submitted = st.form_submit_button("Send magic link")
        if submitted:
            if not email:
                st.error("Enter your email.")
            else:
                try:
                    # Try both call signatures (lib versions differ)
                    try:
                        sb.auth.sign_in_with_otp({"email": email, "options": {"email_redirect_to": APP_BASE_URL or None}})
                    except Exception:
                        sb.auth.sign_in_with_otp(email=email)
                    st.success("Magic link sent! Check your inbox and click the link to come back here.")
                except Exception as e:
                    st.error("Failed to send magic link. Verify SUPABASE_URL/KEY and allowed redirects in Supabase.")
    with st.expander("ℹ️ Configuration tips"):
        st.markdown("""
**Required env vars** (Docker/Compose):
- `SUPABASE_URL` — your project URL (https://xxxx.supabase.co)
- `SUPABASE_ANON_KEY` — anon public key
- `APP_BASE_URL` — the URL users will hit (must be in Supabase Auth redirect allow-list)

**In Supabase Dashboard → Auth → URL Configuration:**
- Set **Site URL** to your `APP_BASE_URL` (e.g., `https://your.domain` or `http://<EC2-IP>:8501`)
- Add `APP_BASE_URL` to **Redirect URLs**.

Then click "Send magic link" — after email click, you return here with `?code=...`.
""")
    return False

if not require_auth_magic_link():
    st.stop()


with st.sidebar:
    st.header("Ustawienia")
    green_thr = st.slider("Próg green (%)", 60, 95, 80)
    amber_thr = st.slider("Próg amber (%)", 40, 80, 60)
    st.caption("N.A. nie wchodzi do mianownika; wagi są wspierane. Yes=1, Partial=0.5, No=0.")

def load_questions(xlsx) -> pd.DataFrame:
    df = pd.read_excel(xlsx, engine="openpyxl")
    df = df.rename(columns={"Podpowiedź":"hint","Hint":"hint"})
    for c in ["section","requirement_ref","question_id","question_text"]:
        if c not in df.columns: df[c] = ""
    if "answer" not in df.columns: df["answer"]="N.A."
    if "weight" not in df.columns: df["weight"]=1.0
    if "hint" not in df.columns: df["hint"]=""
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(1.0).astype(float)
    df["answer"] = df["answer"].fillna("N.A.")
    df["hint"] = df["hint"].fillna("").astype(str)
    return df

def compute_scores(df: pd.DataFrame, green_thr=80, amber_thr=60):
    score_map = {"Yes":1.0,"Partial":0.5,"No":0.0,"N.A.":None}
    df = df.copy()
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(1.0).astype(float)
    df["answer"] = df["answer"].fillna("N.A.")
    df["score"] = df["answer"].map(score_map)
    m = df["score"].notna()
    overall = round(100.0*(df.loc[m,"score"]*df.loc[m,"weight"]).sum()/(df.loc[m,"weight"].sum() or 1.0),1) if m.any() else 0.0
    badge = "green" if overall>=green_thr else ("amber" if overall>=amber_thr else "red")
    section_scores = {}
    for sec, g in df.groupby("section", dropna=False):
        m2 = g["score"].notna()
        section_scores[str(sec)] = round(100.0*(g.loc[m2,"score"]*g.loc[m2,"weight"]).sum()/(g.loc[m2,"weight"].sum() or 1.0),1) if m2.any() else 0.0
    gaps_df = df[df["answer"].isin(["No","Partial"])].copy()
    return overall,badge,section_scores,gaps_df

def render_report(df: pd.DataFrame, green_thr:int, amber_thr:int) -> str:
    overall,badge,sections,gaps = compute_scores(df, green_thr, amber_thr)
    rows = "".join([f"<tr><td>{s}</td><td>{v}%</td></tr>" for s,v in sections.items()])
    gaps_rows = "".join([
        (f"<tr><td>{r.question_id}</td><td>{r.question_text}"
         f"{('<br><small><em>Podpowiedź: '+str(r.hint)+'</em></small>') if str(r.get('hint','')).strip() else ''}"
         f"</td></tr>")
        for _, r in gaps.iterrows()
    ])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html><meta charset='utf-8'><title>DORA Report</title>
<h1>DORA Audit — Raport</h1><p>{now}</p>
<h2>Wynik ogólny: {overall}% — {badge}</h2>
<h3>Wyniki sekcji</h3><table border='1' cellpadding='6'><tr><th>Sekcja</th><th>Wynik</th></tr>{rows}</table>
<h3>Rejestr luk</h3><table border='1' cellpadding='6'><tr><th>ID</th><th>Pytanie</th></tr>{gaps_rows or "<tr><td colspan='2'>Brak luk</td></tr>"} </table>
"""

tab1, tab2 = st.tabs(["Ankieta", "Wyniki i raport"])
with tab1:
    up = st.file_uploader("Wgraj XLSX z pytaniami (obsługa „Podpowiedź”/hint)", type=["xlsx"])
    if up:
        st.session_state["df"] = load_questions(up)
    else:
        if "df" not in st.session_state:
            st.session_state["df"] = pd.DataFrame([
                {"section":"Governance","requirement_ref":"DORA Art.5","question_id":"GOV-01","question_text":"Is there a DORA governance framework?","hint":"Struktura zarządzania obejmuje ryzyka ICT i zgodność?","answer":"Yes","weight":1.0},
                {"section":"Incident Mgmt","requirement_ref":"DORA Art.17","question_id":"INC-01","question_text":"Is there an incident response plan?","hint":"Role, KPI, komunikacja, raportowanie.","answer":"Partial","weight":2.0},
                {"section":"Third-Party","requirement_ref":"DORA Art.28","question_id":"TPM-01","question_text":"Do contracts include audit rights?","hint":"Prawo audytu i dostęp do dowodów.","answer":"No","weight":1.0}
            ])
    df = st.session_state["df"]
    st.subheader("Pytania")
    order = ["Yes","Partial","No","N.A."]
    for i, r in df.iterrows():
        st.markdown(f"**{r.get('question_id','')}** — {r.get('question_text','')}")
        ht = str(r.get("hint","") or "").strip()
        if ht:
            with st.expander("💡 Pokaż podpowiedź"):
                st.info(ht)
        try: idx = order.index(r.get("answer","N.A."))
        except ValueError: idx = order.index("N.A.")
        ans = st.radio("Odpowiedź:", order, index=idx, key=f"ans_{i}", horizontal=True)
        df.at[i,"answer"]=ans
        st.divider()
    st.session_state["df"]=df

with tab2:
    html = render_report(st.session_state.get("df", pd.DataFrame()), green_thr, amber_thr)
    st.download_button("Pobierz raport (HTML)", data=html.encode("utf-8"), file_name="dora_report.html", mime="text/html")
    st.components.v1.html(html, height=460, scrolling=True)
