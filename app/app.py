
import streamlit as st
import pandas as pd
from datetime import datetime

# --- Supabase persistence helpers ---
from datetime import datetime
def _safe_get_user_identity(client):
    try:
        user = client.auth.get_user().user
        if user and user.email:
            return {"id": user.id, "email": user.email}
    except Exception:
        pass
    try:
        ses = st.session_state.get("supabase_session")
        if ses and "user" in ses and ses["user"].get("email"):
            return {"id": ses["user"]["id"], "email": ses["user"]["email"]}
    except Exception:
        pass
    return {"id": None, "email": None}

def save_assessment(client, answers, scores, meta=None):


    # --- Data validation & reporting helpers ---
    import io
    import pandas as pd

    REQUIRED_COLUMNS = ["section","requirement_ref","question_id","question_text","hint","weight","answer"]

    def validate_questions_df(df: pd.DataFrame):
        """Ensure the uploaded XLSX has all required columns with sane types."""
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            st.error(f"Brak kolumn w pliku XLSX: {', '.join(missing)}. Upewnij się, że plik zawiera kolumny: {', '.join(REQUIRED_COLUMNS)}")
            st.stop()
        # normalize types
        df["section"] = df["section"].astype(str)
        df["question_id"] = df["question_id"].astype(str)
        if "weight" in df.columns:
            df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(1.0)

    def build_gap_register(df: pd.DataFrame):
        """Return only gaps (No/Partial) as a DataFrame."""
        if "answer" not in df.columns:
            return pd.DataFrame()
        mask = df["answer"].isin(["No","Partial"])
        cols = [c for c in ["section","requirement_ref","question_id","question_text","answer","hint","weight"] if c in df.columns]
        gaps = df.loc[mask, cols].copy()
        gaps = gaps.rename(columns={
            "requirement_ref":"requirement",
            "question_text":"question"
        })
        return gaps

    def download_gap_register_buttons(gaps_df: pd.DataFrame):
        """Render download buttons for gaps as CSV/XLSX; no-op if empty."""
        if gaps_df.empty:
            st.info("Brak luk do wyeksportowania (wszystko na zielono).")
            return
        # CSV
        csv_bytes = gaps_df.to_csv(index=False).encode("utf-8")
        st.download_button("Pobierz rejestr luk (CSV)", data=csv_bytes, file_name="gap_register.csv", mime="text/csv")

    # --- PDF export ---
    with st.expander("Eksport do PDF", expanded=False):
        if st.button("Wygeneruj PDF z raportu"):
            try:
                pdf_bytes = html_to_pdf_bytes(report_html if 'report_html' in locals() else rendered_html)
                st.download_button("Pobierz raport (PDF)", data=pdf_bytes, file_name="dora_report.pdf", mime="application/pdf")
                st.success("PDF gotowy do pobrania.")
            except ImportError:
                st.info("Aby eksportować do PDF, zainstaluj pakiet **weasyprint** oraz wymagane biblioteki systemowe. Alternatywnie pobierz HTML i użyj „Drukuj → Zapisz jako PDF”.")
            except Exception as e:
                st.error(f"Nie udało się wygenerować PDF: {e}")


    # XLSX
    xls_buf = io.BytesIO()
    with pd.ExcelWriter(xls_buf, engine="xlsxwriter") as writer:
        gaps_df.to_excel(writer, index=False, sheet_name="Gaps")
    st.download_button("Pobierz rejestr luk (XLSX)", data=xls_buf.getvalue(), file_name="gap_register.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

def list_assessments_ui(client):
    """Show previous assessments for the current user in an expander."""
    try:
        user = client.auth.get_user().user
        email = user.email if user else None
    except Exception:
        email = None
    st.subheader("Historia zapisanych ocen")
    if not client or not email:
        st.info("Zaloguj się, aby zobaczyć historię zapisów.")
        return
    try:
        res = client.table("assessments").select("*").eq("email", email).order("created_at", desc=True).limit(50).execute()
        rows = res.data if hasattr(res, "data") else (res.get("data") if isinstance(res, dict) else [])
    except Exception as e:
        st.error(f"Nie udało się pobrać historii: {e}")
        return
    if not rows:
        st.write("Brak zapisanych ocen.")
        return
    # Render compact table
    import pandas as pd
    df_hist = pd.DataFrame(rows)
    # Keep common columns
    keep_cols = [c for c in ["created_at","classification","scores","email","id"] if c in df_hist.columns]
    st.dataframe(df_hist[keep_cols] if keep_cols else df_hist, use_container_width=True)
    # Optional: raw JSON download
    st.download_button("Pobierz historię (JSON)", data=df_hist.to_json(orient="records", force_ascii=False).encode("utf-8"), file_name="assessments_history.json", mime="application/json")



    """
    Insert a row into the 'assessments' table.
    Expected columns in 'assessments':
      - email (text)
      - user_id (uuid) nullable
      - created_at (timestamp) default now() on server is OK but we also send it
      - answers (jsonb)
      - scores (jsonb)
      - meta (jsonb) optional
    """
    ident = _safe_get_user_identity(client)
    payload = {
        "email": ident.get("email"),
        "user_id": ident.get("id"),
        "created_at": datetime.utcnow().isoformat(),
        "answers": answers,
        "scores": scores,
        "meta": meta or {},
    }
    try:
        res = client.table("assessments").insert(payload).execute()
        return True, res
    except Exception as e:
        return False, str(e)


def answers_payload_update_hook(qid, question_text, value, section=None, ref=None):
    try:
        ap = st.session_state.get("answers_payload", {})
        ap[str(qid) if qid is not None else question_text[:64]] = {
            "answer": value,
            "question": question_text,
            "section": section,
            "ref": ref,
        }
        st.session_state["answers_payload"] = ap
    except Exception:
        pass




st.set_page_config(page_title="DORA Compliance - MVP", layout="wide")




# --- HASH → QUERY shim for Supabase magic-link tokens ---
st.markdown("""
<script>
(function () {
  var h = window.location.hash;
  if (h && h.indexOf('access_token=') !== -1) {
    var params = new URLSearchParams(h.substring(1));
    var newUrl = window.location.pathname + "?" + params.toString();
    window.history.replaceState({}, "", newUrl);
    window.location.reload();
  }
})();
</script>
""", unsafe_allow_html=True)
if "answers_payload" not in st.session_state:
    st.session_state["answers_payload"] = {}

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
    validate_questions_df(df)
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


    # --- Optional PDF export (WeasyPrint) ---
    def html_to_pdf_bytes(html: str) -> bytes:
        """
        Try to render HTML to PDF using WeasyPrint. If unavailable, raise ImportError.
        """
        try:
            from weasyprint import HTML, CSS
        except Exception as e:
            raise ImportError("WeasyPrint is not installed or missing system deps") from e
        css = CSS(string="""
            @page { size: A4; margin: 16mm; }
            h1, h2, h3 { page-break-after: avoid; }
            table { width: 100%; border-collapse: collapse; }
            th, td { border: 1px solid #ddd; padding: 6px; }
        """)
        pdf = HTML(string=html).write_pdf(stylesheets=[css])
        return pdf


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
    answers_payload_update_hook(qid if 'qid' in locals() else (row.question_id if 'row' in locals() and hasattr(row,'question_id') else None), (question_text if 'question_text' in locals() else (row.question_text if 'row' in locals() and hasattr(row,'question_text') else '')), ans, section=(section if 'section' in locals() else (row.section if 'row' in locals() and hasattr(row,'section') else None)), ref=(requirement_ref if 'requirement_ref' in locals() else (row.requirement_ref if 'row' in locals() and hasattr(row,'requirement_ref') else None)))
    df.at[i,"answer"]=ans
    st.divider()
    st.session_state["df"]=df

with tab2:
    html = render_report(st.session_state.get("df", pd.DataFrame()), green_thr, amber_thr)
    st.download_button("Pobierz raport (HTML)", data=html.encode("utf-8"), file_name="dora_report.html", mime="text/html")


# --- Save results to Supabase ---
try:
    sb_client = supa()
except Exception:
    sb_client = None
if sb_client:
    st.divider()
    st.subheader("Zapis wyników")
label_name = st.text_input("Nazwa/etykieta tej oceny (opcjonalnie)", value="")
if st.button("Zapisz wynik w Supabase", type="primary"):
    try:
        answers_payload = st.session_state.get("answers_payload") or {}
    except Exception:
        answers_payload = {}
    try:
        scores_payload = {
            "overall": float(total_score) if 'total_score' in locals() else None,
            "by_section": section_scores if 'section_scores' in locals() else {},
            "thresholds": {
                "green": green_threshold if 'green_threshold' in locals() else None,
                "amber": amber_threshold if 'amber_threshold' in locals() else None,
            },
            "classification": overall_label if 'overall_label' in locals() else None,
        }
    except Exception:
        scores_payload = {}
    meta_payload = {"app_version": "fixed-2025-10-11"}
if label_name:
    meta_payload["label"] = label_name
if 'overall_label' in locals():
    meta_payload["classification"] = overall_label
    ok, res = save_assessment(sb_client, answers_payload, scores_payload, meta=meta_payload)
    if ok:
        st.success("Zapisano wynik w tabeli 'assessments'.")
    else:
        st.error(f"Nie udało się zapisać: {res}")
else:
    st.info("Brak klienta Supabase – uzupełnij SUPABASE_URL i SUPABASE_ANON_KEY.")
    st.components.v1.html(html, height=460, scrolling=True)

st.divider()
with st.expander("Historia zapisów (Supabase)", expanded=False):
    try:
        sb = supa()
    except Exception:
        sb = None
    if not sb:
        st.info("Brak klienta Supabase.")
    else:
        # Fetch
        email = None
        try:
            u = sb.auth.get_user().user
            email = u.email if u else None
        except Exception:
            pass
        if not email:
            st.info("Zaloguj się, aby zobaczyć historię.")
        else:
            try:
                res = sb.table("assessments").select("*").eq("email", email).order("created_at", desc=True).limit(200).execute()
                rows = res.data if hasattr(res, "data") else (res.get("data") if isinstance(res, dict) else [])
            except Exception as e:
                st.error(f"Nie udało się pobrać historii: {e}")
                rows = []
            import pandas as pd
            dfh = pd.DataFrame(rows) if rows else pd.DataFrame()
            # Filters
            c1, c2, c3 = st.columns([1,1,1])
            with c1:
                start = st.date_input("Od daty", value=None)
            with c2:
                end = st.date_input("Do daty", value=None)
            with c3:
                classes = ["(wszystkie)"]
                if not dfh.empty:
                    if "classification" in dfh.columns:
                        classes += sorted([x for x in dfh["classification"].dropna().unique().tolist() if isinstance(x, str)])
                    else:
                        classes += ["green","amber","red"]
                cls = st.selectbox("Klasyfikacja", classes, index=0)

            view = dfh.copy()
            if not view.empty and "created_at" in view.columns:
                view["created_at"] = pd.to_datetime(view["created_at"], errors="coerce")
            if start:
                view = view[view["created_at"] >= pd.to_datetime(start)]
            if end:
                view = view[view["created_at"] < (pd.to_datetime(end) + pd.Timedelta(days=1))]
            if cls and cls != "(wszystkie)":
                if "classification" in view.columns:
                    view = view[view["classification"] == cls]
                else:
                    def _class_from_scores(s):
                        try:
                            return (s or {}).get("classification")
                        except Exception:
                            return None
                    if "scores" in view.columns:
                        view["_cls"] = view["scores"].apply(_class_from_scores)
                        view = view[view["_cls"] == cls]

            keep = [c for c in ["created_at","classification","email","id","scores"] if c in view.columns]
            st.dataframe(view[keep] if keep else view, use_container_width=True, height=320)

            # Preview
            st.write("**Podgląd wybranej oceny**")
            ids = view["id"].astype(str).tolist() if "id" in view.columns else []
            chosen = st.selectbox("Wybierz zapis ID", ["(brak)"] + ids, index=0)
            if chosen != "(brak)":
                try:
                    row = view[view["id"].astype(str)==chosen].iloc[0].to_dict()
                    st.caption(f"Utworzono: {row.get('created_at')}  |  E-mail: {row.get('email')}  |  Klasyfikacja: {row.get('classification')}")
                    st.subheader("Scores")
                    st.json(row.get("scores"))
                    answers = row.get("answers") or {}
                    if isinstance(answers, dict):
                        import pandas as pd
                        adf = pd.DataFrame([
                            {
                                "section": v.get("section"),
                                "requirement": v.get("ref"),
                                "question_id": k,
                                "question": v.get("question"),
                                "answer": v.get("answer")
                            } for k, v in answers.items()
                        ])
                        if not adf.empty:
                            gaps = adf[adf["answer"].isin(["No","Partial"])]
                            st.subheader("Luki w tym zapisie")
                            if gaps.empty:
                                st.write("Brak luk.")
                            else:
                                st.dataframe(gaps, use_container_width=True)
                                import io
                                csvb = gaps.to_csv(index=False).encode("utf-8")
                                st.download_button("Pobierz luki (CSV) dla tego zapisu", data=csvb, file_name=f"gaps_{chosen}.csv", mime="text/csv")
                except Exception as e:
                    st.error(f"Nie udało się zbudować podglądu: {e}")
