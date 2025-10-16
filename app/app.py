
import os
import streamlit as st
from supabase import create_client
from supabase.client import Client  # ✅ DODAJ TO
import pandas as pd
# ADD: imports for admin/user panels
from io import BytesIO
from datetime import datetime

SITE_BASE_URL = os.getenv("SITE_BASE_URL", "http://51.21.152.197:8080")

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
    st.dataframe(df_hist[keep_cols] if keep_cols else df_hist, width='stretch')
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

# ADD: DB helpers

def is_admin(client: Client, email: str) -> bool:
    try:
        res = client.table("user_roles").select("is_admin").eq("email", email).maybe_single().execute()
        row = getattr(res, "data", None) or (isinstance(res, dict) and res.get("data"))
        return bool(row and row.get("is_admin"))
    except Exception:
        return False

def list_questionnaires(client: Client):
    res = client.table("questionnaires").select("*").order("created_at", desc=True).execute()
    return getattr(res, "data", []) or []

def upsert_questionnaire(client: Client, title: str, file_path: str | None,
                         green: float, amber: float, created_by: str):
    payload = {
        "title": title.strip(),
        "file_path": file_path,
        "green_threshold": float(green),
        "amber_threshold": float(amber),
        "created_by": created_by
    }
    return client.table("questionnaires").insert(payload).execute()

def upload_questionnaire_file(client: Client, file_name: str, data: bytes) -> str:
    # zapis do Storage (bucket: questionnaires)
    # unikalna ścieżka: YYYY/MM/DD/HHMMSS_filename
    now = datetime.utcnow().strftime("%Y/%m/%d/%H%M%S")
    path = f"{now}_{file_name}"
    client.storage.from_("questionnaires").upload(path, data, {"contentType": "application/octet-stream", "upsert": True})
    return path

def my_instances(client: Client, email: str):
    res = client.table("survey_instances") \
        .select("id, questionnaire_id, status, progress, updated_at, created_at") \
        .eq("email", email).order("updated_at", desc=True).execute()
    return getattr(res, "data", []) or []

def start_new_instance(client: Client, q_id: str, email: str):
    payload = {"questionnaire_id": q_id, "email": email, "status": "in_progress", "progress": 0, "answers": {}}
    return client.table("survey_instances").insert(payload).execute()

def update_progress(client: Client, instance_id: str, progress: int, answers: dict | None = None, status: str | None = None):
    payload = {"progress": int(progress), "updated_at": datetime.utcnow().isoformat()}
    if answers is not None:
        payload["answers"] = answers
    if status:
        payload["status"] = status
    return client.table("survey_instances").update(payload).eq("id", instance_id).execute()

# === PARSER ANKIETY ===

def storage_download_bytes(client: Client, bucket: str, path: str) -> bytes:
    """Pobierz plik z Supabase Storage jako bytes."""
    res = client.storage.from_(bucket).download(path)
    # supabase-py może zwrócić bytes albo obiekt z 'data'
    if isinstance(res, (bytes, bytearray)):
        return bytes(res)
    if isinstance(res, dict) and "data" in res and isinstance(res["data"], (bytes, bytearray)):
        return bytes(res["data"])
    # niektóre wersje mają atrybut .data
    data = getattr(res, "data", None)
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    raise RuntimeError("Nie udało się pobrać pliku ze Storage.")

def _coerce_bool(v, default=True):
    if v is None: return default
    s = str(v).strip().lower()
    return s in ("1","true","t","yes","y")

def _parse_options(s: str | None):
    """Parsuje 'Label=1 | X=0.5' → [(label, weight), ...]."""
    if not s or not str(s).strip():
        return []
    parts = [p.strip() for p in str(s).split("|")]
    out = []
    for p in parts:
        if "=" in p:
            lab, w = p.split("=", 1)
            try:
                out.append((lab.strip(), float(w.strip())))
            except Exception:
                out.append((lab.strip(), 1.0))
        else:
            out.append((p.strip(), 1.0))
    return out

def parse_questionnaire_df(df: pd.DataFrame):
    """Zwraca listę sekcji: [{"name": str, "questions": [q,...]}] z polami w q."""
    # normalizacja kolumn
    cols = {c.lower().strip(): c for c in df.columns}
    require = lambda k: cols.get(k, k)
    get = lambda row, key, default=None: row.get(require(key), default)

    records = []
    for _, row in df.rename(columns=lambda c: c.lower().strip()).iterrows():
        qtype = str(get(row, "type", "yesno")).strip().lower()
        rec = {
            "section":  str(get(row, "section", "General")).strip(),
            "code":     str(get(row, "code", "")).strip() or f"Q{len(records)+1:03d}",
            "title":    str(get(row, "title", "")).strip(),
            "type":     qtype,
            "options":  _parse_options(get(row, "options")),
            "weight":   float(get(row, "weight", 1) or 1),
            "required": _coerce_bool(get(row, "required", True), default=True),
            "help":     str(get(row, "help", "") or "").strip(),
            "min":      None if pd.isna(get(row, "min", None)) else float(get(row, "min")),
            "max":      None if pd.isna(get(row, "max", None)) else float(get(row, "max")),
        }
        records.append(rec)

    # grupowanie w sekcje
    sections = {}
    for q in records:
        sections.setdefault(q["section"], []).append(q)
    return [{"name": name, "questions": qs} for name, qs in sections.items()]

def load_questionnaire_from_storage(client: Client, file_path: str):
    """Wczytuje plik z bucketu 'questionnaires' i zwraca sekcje + pytania."""
    data = storage_download_bytes(client, "questionnaires", file_path)
    name = file_path.lower()
    if name.endswith(".xlsx") or name.endswith(".xls"):
        df = pd.read_excel(BytesIO(data))
    elif name.endswith(".csv"):
        df = pd.read_csv(BytesIO(data))
    elif name.endswith(".json"):
        # JSON: tablica obiektów (keys jak w CSV)
        df = pd.json_normalize(pd.read_json(BytesIO(data)))
    else:
        raise ValueError("Nieobsługiwane rozszerzenie (dozwolone: .xlsx, .csv, .json)")
    return parse_questionnaire_df(df)

# === SCORING ===

def _score_yesno(value, weight):
    # True/Yes → 1, reszta 0
    v = 1.0 if (str(value).lower() in ("1","true","t","yes","y")) else 0.0
    return v * weight, weight

def _score_single(value, options, weight):
    if value is None or value == "": return 0.0, weight
    # znajdź wagę opcji
    d = dict(options) if options else {}
    w = d.get(value, 1.0)
    return float(w) * weight, weight

def _score_multi(values, options, weight):
    if not values: return 0.0, weight
    d = dict(options) if options else {}
    if d:
        s = sum(d.get(v, 0.0) for v in values)
        # normalizacja do [0,1] przy opcji z max sumą? tutaj zostawiamy "sumę wprost"
        # aby uniknąć przekroczeń, przyjmijmy max = suma wag
        max_sum = sum(d.values()) or 1.0
        ratio = min(1.0, s / max_sum)
        return ratio * weight, weight
    # bez wag: 1/N każda
    ratio = min(1.0, len(values) / max(1, len(values)))
    return ratio * weight, weight

def _score_scale(value, qmin, qmax, weight):
    if value is None or qmin is None or qmax is None: return 0.0, weight
    try:
        v = float(value)
        if qmax == qmin: return 0.0, weight
        ratio = (v - qmin) / (qmax - qmin)
        ratio = max(0.0, min(1.0, ratio))
        return ratio * weight, weight
    except Exception:
        return 0.0, weight

def _score_number(value, qmin, qmax, weight):
    # jak scale – normalizacja
    return _score_scale(value, qmin, qmax, weight)

def compute_result(sections, answers: dict, green=80.0, amber=60.0):
    """Zwraca: dict(score_pct, color, required_total, required_answered, progress_pct)."""
    total_w = 0.0
    got_w = 0.0
    required_total = 0
    required_answered = 0

    for sec in sections:
        for q in sec["questions"]:
            wt = float(q.get("weight", 1) or 1)
            total_w += wt
            code = q["code"]
            qtype = q["type"]
            val = answers.get(code)
            if q.get("required", True):
                required_total += 1
                if val not in (None, "", []):  # prosta heurystyka
                    required_answered += 1

            if qtype == "yesno":
                s, w = _score_yesno(val, wt)
            elif qtype == "single":
                s, w = _score_single(val, q.get("options"), wt)
            elif qtype == "multi":
                s, w = _score_multi(val, q.get("options"), wt)
            elif qtype == "scale":
                s, w = _score_scale(val, q.get("min"), q.get("max"), wt)
            elif qtype == "number":
                s, w = _score_number(val, q.get("min"), q.get("max"), wt)
            else:  # text / inne nie wpływają na wynik
                s, w = 0.0, 0.0
                total_w -= wt  # nie licz do denominatora
            got_w += s

    score_pct = 0.0 if total_w <= 0 else (got_w / total_w) * 100.0
    progress_pct = 0.0 if required_total <= 0 else (required_answered / required_total) * 100.0

    color = "green" if score_pct >= green else ("amber" if score_pct >= amber else "red")
    return {
        "score_pct": round(score_pct, 1),
        "color": color,
        "required_total": required_total,
        "required_answered": required_answered,
        "progress_pct": int(round(progress_pct)),
    }

# === RENDERER INSTANCJI ===

def render_instance_form(client: Client, instance_row: dict, qdef_row: dict):
    """Pełny formularz dla danej instancji + zapis postępu i wyniku."""
    # 1) wczytaj definicję pytań
    sections = []
    if qdef_row.get("file_path"):
        try:
            sections = load_questionnaire_from_storage(client, qdef_row["file_path"])
        except Exception as e:
            st.error(f"Nie udało się wczytać ankiety: {e}")
            return

    answers = instance_row.get("answers") or {}
    if isinstance(answers, str):
        try: answers = json.loads(answers)
        except Exception: answers = {}

    st.markdown(f"**Ankieta:** {qdef_row.get('title','(bez nazwy)')}")

    with st.form(f"form_{instance_row['id']}", border=False):
        # 2) rendery pytań
        for sec in sections:
            with st.expander(sec["name"], expanded=True):
                for q in sec["questions"]:
                    code = q["code"]
                    qtype = q["type"]
                    help_ = q.get("help") or ""
                    key = f"{instance_row['id']}_{code}"

                    if qtype == "yesno":
                        current = bool(str(answers.get(code, "")).lower() in ("1","true","t","yes","y"))
                        v = st.checkbox(q["title"], value=current, help=help_, key=key)
                        answers[code] = v

                    elif qtype == "single":
                        opts = [o[0] for o in (q.get("options") or [])] or ["No","Yes"]
                        current = answers.get(code) if answers.get(code) in opts else None
                        v = st.radio(q["title"], opts, index=(opts.index(current) if current in opts else 0), help=help_, key=key)
                        answers[code] = v

                    elif qtype == "multi":
                        opts = [o[0] for o in (q.get("options") or [])]
                        if not opts:  # fallback
                            opts = ["Option A","Option B","Option C"]
                        current = answers.get(code) or []
                        v = st.multiselect(q["title"], opts, default=[x for x in current if x in opts], help=help_, key=key)
                        answers[code] = v

                    elif qtype == "scale":
                        qmin = int(q.get("min") or 1)
                        qmax = int(q.get("max") or 5)
                        current = int(answers.get(code) or qmin)
                        v = st.slider(q["title"], qmin, qmax, current, help=help_, key=key)
                        answers[code] = v

                    elif qtype == "number":
                        qmin = float(q.get("min") or 0)
                        qmax = float(q.get("max") or 100)
                        current = float(answers.get(code) or qmin)
                        v = st.number_input(q["title"], min_value=qmin, max_value=qmax, value=current, step=1.0, help=help_, key=key)
                        answers[code] = v

                    else:  # text / inne
                        current = str(answers.get(code) or "")
                        v = st.text_input(q["title"], value=current, help=help_, key=key)
                        answers[code] = v

        submitted = st.form_submit_button("Zapisz")
        if submitted:
            # 3) policz wynik + progres wg progów z definicji
            res = compute_result(
                sections,
                answers,
                green=float(qdef_row.get("green_threshold", 80.0) or 80.0),
                amber=float(qdef_row.get("amber_threshold", 60.0) or 60.0),
            )
            status = "completed" if res["progress_pct"] == 100 else "in_progress"
            try:
                update_progress(client, instance_row["id"], res["progress_pct"], answers, status=status)
                st.success(f"Zapisano. Wynik: {res['score_pct']}% → {res['color'].upper()} • Progres: {res['progress_pct']}%")
                st.session_state["current_progress"] = res["progress_pct"]
            except Exception as e:
                st.error(f"Nie udało się zapisać: {e}")


st.set_page_config(page_title="DORA Compliance - MVP", layout="wide")

# === SITE THEME: spójny wygląd z /site ===
SITE_CSS = """
/* reset + ciemny motyw jak w /site */
:root {
  --bg: #0e0e10; --panel: #17171b; --muted: #a7a7ad; --text: #e5e7eb; --primary: #7c3aed;
  --radius: 14px;
}
html, body { background: var(--bg); }
section.main > div { padding-top: 12px; }
.block-container { max-width: 980px; padding: 24px 16px; }
.stMarkdown, .stText, .stCaption, .stExpander, .stDownloadButton { color: var(--text); }
h1, h2, h3, h4 { color: var(--text); letter-spacing: .2px; }
hr { border-color: #26262b; }
.stExpander { border: 1px solid #26262b; border-radius: var(--radius); background: transparent; }

.stTextInput > div > div > input,
.stTextArea textarea,
[data-baseweb="select"] > div {
  background: var(--panel) !important; color: var(--text) !important;
  border: 1px solid #26262b !important; border-radius: var(--radius) !important;
}

.stButton>button {
  background: var(--primary) !important; color: white !important; border: 0 !important;
  border-radius: 12px !important; padding: 10px 16px !important; font-weight: 600;
}
.stButton>button:hover { filter: brightness(1.05); }

.st-emotion-cache-ue6h4q { color: var(--muted) !important; }   /* helper dla captionów */
.stAlert { background: #141419; border: 1px solid #26262b; border-radius: var(--radius); }
"""

def apply_site_theme():
    st.markdown(f"<style>{SITE_CSS}</style>", unsafe_allow_html=True)

apply_site_theme()

import streamlit as st
import streamlit.components.v1 as components

# --- HASH → QUERY shim (działa w iframe; odwołanie do parent.location) ---
components.html("""
<script>
(function () {
  try {
    var h = parent.location.hash || "";
    var hasAuth = h.indexOf('access_token=') !== -1 || h.indexOf('refresh_token=') !== -1 || h.indexOf('code=') !== -1;
    if (hasAuth) {
      var s = document.createElement('style'); s.innerHTML='body{visibility:hidden}'; document.head.appendChild(s);
      var params = new URLSearchParams(h.substring(1)); // obetnij '#'
      var newUrl = parent.location.pathname + "?" + params.toString();
      parent.history.replaceState({}, "", newUrl);
      parent.location.reload();
    }
  } catch (e) {
    // cicho ignoruj
  }
})();
</script>
""", height=0)

if "answers_payload" not in st.session_state:
    st.session_state["answers_payload"] = {}


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
    client = supa()

    # a) Obsługa powrotu z magic-linka: ?code=...
    qp = st.query_params if hasattr(st, "query_params") else st.experimental_get_query_params()
    code = None
    if isinstance(qp, dict):
        raw_code = qp.get("code")
        if isinstance(raw_code, list): code = raw_code[0]
        elif isinstance(raw_code, str): code = raw_code

    if code:
        with st.spinner("Signing you in…"):
            try:
                data = client.auth.exchange_code_for_session({"auth_code": code})
                session = getattr(data, "session", None) or (isinstance(data, dict) and data.get("session"))
                access = getattr(session, "access_token", None) or (session and session.get("access_token"))
                refresh = getattr(session, "refresh_token", None) or (session and session.get("refresh_token"))
                if access and refresh:
                    st.session_state["access_token"] = access
                    st.session_state["refresh_token"] = refresh
                    client.auth.set_session(access, refresh)
                    try: st.query_params.clear()
                    except Exception: st.experimental_set_query_params()
                    st.rerun()
            except Exception:
                st.error("Nie udało się wymienić code → session.")
                try: st.query_params.clear()
                except Exception: st.experimental_set_query_params()
                st.stop()

    # b) Obsługa powrotu z #access_token / #refresh_token (zamienione na query w JS)
    access = refresh = None
    if isinstance(qp, dict):
        ra, rr = qp.get("access_token"), qp.get("refresh_token")
        access  = ra[0] if isinstance(ra, list) else ra
        refresh = rr[0] if isinstance(rr, list) else rr

    if access and refresh:
        try:
            client.auth.set_session(access, refresh)
            st.session_state["access_token"] = access
            st.session_state["refresh_token"] = refresh
            try: st.query_params.clear()
            except Exception: st.experimental_set_query_params()
            st.rerun()
        except Exception:
            pass

    # c) Mamy zapamiętane tokeny?
    at, rt = st.session_state.get("access_token"), st.session_state.get("refresh_token")
    if at and rt:
        try:
            client.auth.set_session(at, rt)
            u = client.auth.get_user()
            if u:
                return True
        except Exception:
            st.session_state.pop("access_token", None)
            st.session_state.pop("refresh_token", None)

    # d) Brak sesji — pokaż „kartę” z linkiem do strony logowania (z /site)
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


if not require_auth_magic_link():
    st.stop()

# Po pomyślnym logowaniu — sprawdź uprawnienia
_enforce_allowed_email(supa())

email = _get_current_user_email(supa()) or ""
admin = is_admin(supa(), email)

# tytuł po zalogowaniu
st.title("DORA Audit — MVP")

# nawigacja (sidebar)
page = st.sidebar.radio("Nawigacja", ["Moje ankiety"] + (["Panel administracyjny"] if admin else []))

if page == "Panel administracyjny":
    render_admin_panel(supa(), email)
else:
    render_user_panel(supa(), email)

st.title("DORA Audit — MVP")

# ======== SESSION BAR (Supabase) ========
from datetime import datetime, timezone
import time

# Compat: st.rerun (new) / st.experimental_rerun (old)
def _st_rerun():
    fn = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
    if callable(fn):
        fn()

def _get_session_safe(sb):
    """Supabase-py bywa różne w zależności od wersji – tu bezpieczny odczyt sesji."""
    try:
        sess = sb.auth.get_session()
    except Exception:
        sess = None
    # Obsłuż obiekt i dict
    if hasattr(sess, "access_token"):
        access_token = getattr(sess, "access_token", None)
        refresh_token = getattr(sess, "refresh_token", None)
        user = getattr(sess, "user", None)
        email = getattr(user, "email", None) if user else None
        # v2 zwykle ma epoch w 'expires_at'
        exp = getattr(sess, "expires_at", None)
    elif isinstance(sess, dict):
        access_token = sess.get("access_token")
        refresh_token = sess.get("refresh_token")
        email = ((sess.get("user") or {}).get("email"))
        exp = sess.get("expires_at")
    else:
        access_token = refresh_token = email = exp = None
    # W niektórych wersjach brak expires_at → wylicz z now + 3600 jako fallback
    if not exp:
        exp = int(time.time()) + 3600
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "email": email,
        "expires_at": int(exp),
    }

def _refresh_session_safe(sb):
    """Spróbuj odświeżyć sesję (różne wersje klienta)."""
    try:
        # supabase-py v2
        sb.auth.refresh_session()
        return True, "refreshed"
    except Exception as e1:
        # Fallback – jeśli mamy refresh_token zapisany lokalnie
        try:
            s = _get_session_safe(sb)
            if s["refresh_token"]:
                # W wielu wersjach set_session() przyjmuje (access, refresh); access może być None
                sb.auth.set_session(s.get("access_token"), s["refresh_token"])
                return True, "set_session via refresh_token"
        except Exception as e2:
            return False, f"refresh failed: {e1} / {e2}"
    return False, "unknown"

# ======== SESSION AUTO-REFRESH + DEBUG LOG ========
import time
import streamlit as st

def _log_supabase_error(msg, exc=None):
    logs = st.session_state.setdefault("_supabase_logs", [])
    if exc:
        msg = f"{msg}: {exc}"
    logs.append(msg)

def _get_session_info(sb):
    """Zwraca {'email', 'expires_at'} z bezpiecznym fallbackiem."""
    try:
        sess = sb.auth.get_session()
    except Exception as e:
        _log_supabase_error("get_session failed", e)
        sess = None
    user = getattr(sess, "user", None)
    email = getattr(user, "email", None) if user else None
    exp = getattr(sess, "expires_at", None)
    if not exp:
        exp = int(time.time()) + 3600
    return {"email": email, "expires_at": int(exp)}

def auto_refresh_session(sb, warn_at=180, reload_delay=30):
    """
    Gdy do wygaśnięcia ≤ warn_at (s), spróbuj odświeżyć sesję raz na cykl.
    Jeśli nie wyjdzie – zaplanuj miękki reload po 'reload_delay' sekundach.
    """
    s = _get_session_info(sb)
    now = int(time.time())
    remaining = s["expires_at"] - now
    if remaining <= warn_at:
        st.sidebar.warning(f"Session expires in {max(0, remaining)//60}m {max(0, remaining)%60}s")
        # próbuj odświeżyć max 1x na cykl
        if not st.session_state.get("_did_refresh_attempt"):
            st.session_state["_did_refresh_attempt"] = True
            try:
                sb.auth.refresh_session()
                st.sidebar.success("Session refreshed")
                _st_rerun()
                return
            except Exception as e:
                _log_supabase_error("refresh_session failed", e)
        # fallback: miękki reload raz
        if not st.session_state.get("_soft_reload_scheduled"):
            st.session_state["_soft_reload_scheduled"] = True
            st.components.v1.html(
                f"<script>setTimeout(function(){{ parent.location.reload(); }}, {reload_delay*1000});</script>",
                height=0
            )

def show_supabase_debug_panel():
    """Panel w sidebarze z ostatnimi błędami Supabase."""
    with st.sidebar.expander("🛠 Debug (Supabase)", expanded=False):
        logs = st.session_state.get("_supabase_logs") or []
        if logs:
            for i, m in enumerate(logs[-50:], 1):
                st.text(f"{i:02d}. {m}")
        else:
            st.caption("Brak błędów.")
# ======== END ========

def session_bar():
    sb = supa()
    if not sb:
        return  # auth wyłączone

    s = _get_session_safe(sb)
    now = int(time.time())
    remaining = max(0, s["expires_at"] - now)
    exp_dt = datetime.fromtimestamp(s["expires_at"], tz=timezone.utc).astimezone()  # lokalny czas

    with st.sidebar:
        st.markdown("### 🔐 Session")
        st.write(f"**User:** {s['email'] or 'unknown'}")
        st.write(f"**Expires:** {exp_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        st.write(f"**Time left:** {remaining // 60} min {remaining % 60} s")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Refresh session", width='stretch'):
                ok, msg = _refresh_session_safe(sb)
                if ok:
                    st.success("Session refreshed.")
                    _st_rerun()
                else:
                    st.warning(f"Could not refresh: {msg}")
        with col2:
            if st.button("Sign out", width='stretch'):
                try:
                    sb.auth.sign_out()
                except Exception:
                    pass
                st.session_state.pop("auth_ok", None)
                st.session_state.pop("auth_user", None)
                st.components.v1.html("""
                <script>
                  (function(){
                    var clean = parent.location.pathname;
                    parent.history.replaceState({}, "", clean);
                  })();
                </script>
                """, height=0)
                _st_rerun()

        # Ostrzegaj / odświeżaj w tle, gdy kończy się ważność
        if remaining <= 120:
            st.warning("Session is about to expire.")
            # delikatne auto-odświeżenie interfejsu, by zaciągnąć nowe tokeny (jeśli refresh działa)
            _st_rerun()


# Wywołanie paska sesji
session_bar()
# ======== END SESSION BAR ========

# ADD: Admin panel
def render_admin_panel(client: Client, admin_email: str):
    st.subheader("Panel administracyjny")

    with st.expander("➕ Dodaj ankietę", expanded=True):
        title = st.text_input("Tytuł ankiety", placeholder="Nazwa ankiety")
        colA, colB, colC = st.columns(3)
        with colA:
            green = st.number_input("Próg GREEN (%)", min_value=0.0, max_value=100.0, value=80.0, step=1.0)
        with colB:
            amber = st.number_input("Próg AMBER (%)", min_value=0.0, max_value=100.0, value=60.0, step=1.0)
        with colC:
            st.caption("RED = poniżej AMBER (automatycznie)")

        file = st.file_uploader("Plik ankiety (np. XLSX/CSV/JSON)", type=["xlsx","csv","json"], accept_multiple_files=False)
        if st.button("Zapisz ankietę"):
            if not title.strip():
                st.error("Podaj tytuł.")
            else:
                file_path = None
                if file is not None:
                    data = file.read()
                    try:
                        file_path = upload_questionnaire_file(client, file.name, data)
                    except Exception as e:
                        st.error(f"Upload nieudany: {e}")
                        return
                try:
                    upsert_questionnaire(client, title, file_path, green, amber, admin_email)
                    st.success("Ankieta zapisana.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Błąd zapisu ankiety: {e}")

    st.markdown("### 📋 Lista ankiet")
    items = list_questionnaires(client)
    if not items:
        st.info("Brak ankiet.")
    else:
        for q in items:
            with st.container(border=True):
                st.markdown(f"**{q['title']}**  \nGREEN ≥ {q.get('green_threshold',0)}%  •  AMBER ≥ {q.get('amber_threshold',0)}%")
                if q.get("file_path"):
                    st.caption(f"Plik: `{q['file_path']}`")

# ADD: User panel
def render_user_panel(client: Client, email: str):
    st.subheader("Moje ankiety")

    # start od nowa (z dostępnych definicji)
    defs = list_questionnaires(client)
    if defs:
        with st.expander("➕ Rozpocznij nową ankietę", expanded=True):
            options = {f"{d['title']} (GREEN {d.get('green_threshold',0)}% / AMBER {d.get('amber_threshold',0)}%)": d['id'] for d in defs}
            pick = st.selectbox("Wybierz ankietę", list(options.keys()))
            if st.button("Zacznij nową"):
                try:
                    start_new_instance(client, options[pick], email)
                    st.success("Utworzono nową instancję ankiety.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Nie udało się utworzyć ankiety: {e}")
    else:
        st.info("Administrator nie dodał jeszcze żadnych ankiet.")

    st.markdown("### 🔄 Kontynuuj / podgląd")
    rows = my_instances(client, email)
    if not rows:
        st.caption("Brak rozpoczętych ankiet.")
        return

    for r in rows:
        pid = r["id"]
        prog = r.get("progress", 0)
        status = r.get("status", "in_progress")
        cols = st.columns([5,2,2,3])
        with cols[0]:
            st.markdown(f"**Instancja:** `{pid[:8]}…`  \nStatus: `{status}`")
        with cols[1]:
            st.progress(int(prog)/100.0, text=f"{prog}%")
        with cols[2]:
            if st.button("Kontynuuj", key=f"cont_{pid}"):
                st.session_state["current_instance_id"] = pid
                st.session_state["current_progress"] = prog
                st.success("Załadowano ankietę do kontynuacji (tu umieść render formularza).")
        with cols[3]:
            if st.button("Od nowa", key=f"restart_{pid}"):
                # tworzymy nową instancję na tej samej definicji
                try:
                    start_new_instance(client, r["questionnaire_id"], email)
                    st.success("Utworzono nową, pustą instancję.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Nie udało się: {e}")

    # Placeholder: jeżeli chcesz pokazać formularz dla wybranej instancji
    cur = st.session_state.get("current_instance_id")
    if cur:
        st.markdown("---")
        st.markdown(f"#### Wypełnianie ankiety: `{cur[:8]}…`")

        # pobierz pełny wiersz instancji + definicję ankiety (progi + plik)
        try:
            inst_res = client.table("survey_instances").select("*").eq("id", cur).maybe_single().execute()
            instance_row = getattr(inst_res, "data", None) or (isinstance(inst_res, dict) and inst_res.get("data"))
            if not instance_row:
                st.error("Nie znaleziono instancji.")
                return
            q_res = client.table("questionnaires").select("*").eq("id", instance_row["questionnaire_id"]).maybe_single().execute()
            qdef_row = getattr(q_res, "data", None) or (isinstance(q_res, dict) and q_res.get("data"))
            if not qdef_row:
                st.error("Nie znaleziono definicji ankiety.")
                return
        except Exception as e:
            st.error(f"Błąd pobierania danych: {e}")
            return

        render_instance_form(client, instance_row, qdef_row)



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
            st.dataframe(view[keep] if keep else view, width='stretch', height=320)

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
                                st.dataframe(gaps, width='stretch')
                                import io
                                csvb = gaps.to_csv(index=False).encode("utf-8")
                                st.download_button("Pobierz luki (CSV) dla tego zapisu", data=csvb, file_name=f"gaps_{chosen}.csv", mime="text/csv")
                except Exception as e:
                    st.error(f"Nie udało się zbudować podglądu: {e}")


# ======== LOGIN STATUS HEADER ========
import streamlit as st

def login_header():
    sb = supa()
    if not sb:
        return
    try:
        u = sb.auth.get_user().user
        email = getattr(u, "email", None) if u else None
    except Exception:
        email = st.session_state.get("auth_user")
    if not email:
        return
    col1, col2 = st.columns([4, 1])
    with col1:
        st.success(f"✅ Zalogowano jako **{email}**")
    with col2:
        if st.button("Wyloguj się", width='stretch'):
            try:
                sb.auth.sign_out()
            except Exception:
                pass
            st.session_state.pop("auth_ok", None)
            st.session_state.pop("auth_user", None)
            st.components.v1.html("""
            <script>
              (function(){
                var clean = parent.location.pathname;
                parent.history.replaceState({}, "", clean);
              })();
            </script>
            """, height=0)
            _st_rerun()

# Wyświetl nagłówek logowania nad treścią aplikacji
login_header()
# ======== END LOGIN STATUS HEADER ========
