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
from postgrest.exceptions import APIError  # <-- nowy import

def qexec(q):
    """
    Bezpieczne wykonanie zapytań supabase-py v2.
    Zwraca listę (resp.data), a w razie błędu rzuca RuntimeError.
    """
    try:
        resp = q.execute()
        return resp.data or []
    except APIError as e:
        # APIError pochodzi z PostgREST – ma message, code itd.
        raise RuntimeError(f"DB error: {getattr(e, 'message', str(e))}") from e
    except Exception as e:
        raise RuntimeError(f"DB error: {e}") from e

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

    rows = qexec(
        client.table("allowed_emails")
              .select("email")
              .eq("email", email)
              .limit(1)
    )
    if not rows:
        ui_card(
            "⛔ Brak dostępu",
            f"<p class='muted'>Adres <b>{email}</b> nie znajduje się na liście dozwolonych użytkowników.</p>",
            f"<a class='btn' href='{SITE_BASE_URL}/DORA_Checkout_and_FAQ.html'>➡️ Przejdź do: Checkout & FAQ</a>"
        )
        st.stop()

def is_admin(client: Client, email: str) -> bool:
    if not email:
        return False
    rows = qexec(
        client.table("allowed_emails")
              .select("is_admin")
              .eq("email", email)
              .limit(1)
    )
    return bool(rows and rows[0].get("is_admin"))

# =============================================================================
#  Ankiety / wersje (survey + survey_versions)
# =============================================================================
def _get_or_create_survey(client: Client) -> Dict[str, Any]:
    # 1) Spróbuj odczytać istniejącą
    rows = qexec(
        client.table("surveys")
              .select("*")
              .eq("name", SURVEY_NAME)
              .limit(1)
    )
    if rows:
        return rows[0]

    # 2) Wstaw nową
    ins_rows = qexec(
        client.table("surveys").insert({"name": SURVEY_NAME})
    )
    if ins_rows:
        return ins_rows[0]

    # (race condition fallback) – odczytaj ponownie
    rows2 = qexec(
        client.table("surveys")
              .select("*")
              .eq("name", SURVEY_NAME)
              .limit(1)
    )
    if not rows2:
        raise RuntimeError("Survey utworzony, ale nie udało się go odczytać.")
    return rows2[0]

def _next_version_number(client: Client, survey_id: str) -> int:
    rows = qexec(
        client.table("survey_versions")
              .select("version")
              .eq("survey_id", survey_id)
              .order("version", desc=True)
              .limit(1)
    )
    if rows:
        return int(rows[0]["version"]) + 1
    return 1

def _set_active_version(client: Client, survey_id: str, version_id: str) -> None:
    # Wyłącz wszystkie
    qexec(
        client.table("survey_versions")
              .update({"is_active": False})
              .eq("survey_id", survey_id)
    )
    # Włącz wskazaną
    qexec(
        client.table("survey_versions")
              .update({"is_active": True})
              .eq("id", version_id)
    )

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

    ins_rows = qexec(
        client.table("survey_versions").insert({
            "survey_id":       survey_id,
            "version":         version_no,
            "content":         content,
            "threshold_green": int(threshold_green),
            "threshold_amber": int(threshold_amber),
            "created_by":      created_by,
            "is_active":       False,
        })
    )

    if ins_rows:
        ver = ins_rows[0]
    else:
        # fallback: odczytaj świeżo zapisaną wersję
        rows = qexec(
            client.table("survey_versions")
                  .select("*")
                  .eq("survey_id", survey_id)
                  .eq("version", version_no)
                  .limit(1)
        )
        if not rows:
            raise RuntimeError("Wersja zapisana, ale nie udało się jej odczytać.")
        ver = rows[0]

    if set_active:
        _set_active_version(client, survey_id, ver["id"])
        ver["is_active"] = True

    return ver

def _load_active_version(client: Client) -> Optional[Dict[str, Any]]:
    survey = _get_or_create_survey(client)
    rows = qexec(
        client.table("survey_versions")
              .select("*")
              .eq("survey_id", survey["id"])
              .eq("is_active", True)
              .limit(1)
    )
    if rows:
        return rows[0]
    return None

def _list_versions(client: Client) -> List[Dict[str, Any]]:
    survey = _get_or_create_survey(client)
    rows = qexec(
        client.table("survey_versions")
              .select("id, version, created_at, threshold_green, threshold_amber, is_active, created_by")
              .eq("survey_id", survey["id"])
              .order("version", desc=True)
    )
    return rows


def _score_answer(q: Dict[str, Any], value) -> float:
    """Liczy punktację dla pojedynczego pytania zgodnie z typem."""
    t = q.get("type")
    if t == "single":
        # value = etykieta; szukamy opcji i bierzemy jej score
        for opt in q.get("options", []):
            if opt.get("label") == value:
                return float(opt.get("score", 0))
        return 0.0
    elif t == "multi":
        # value = lista etykiet; sumujemy score opcji
        total = 0.0
        selected = value or []
        for opt in q.get("options", []):
            if opt.get("label") in selected:
                total += float(opt.get("score", 0))
        return total
    elif t == "scale":
        # value = liczba; przelicznik na punkty
        mn = q.get("min", 1)
        step_score = float(q.get("score_per_step", 0))
        try:
            return max(0.0, (float(value) - float(mn)) * step_score)
        except Exception:
            return 0.0
    return 0.0

import io

def _answers_map(answers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """question_id -> value (już rozpakowane)"""
    out: Dict[str, Any] = {}
    for a in answers or []:
        out[a["question_id"]] = (a.get("answer") or {}).get("value")
    return out

def _wide_row_for_session(version: Dict[str, Any],
                          session: Dict[str, Any],
                          answers: List[Dict[str, Any]]) -> Tuple[List[str], List[Any]]:
    """Zwraca: (nagłówki, wartości) dla jednej sesji."""
    qs_by_id = _questions_by_id(version)
    qids = list(qs_by_id.keys())            # kolejność jak w wersji
    amap = _answers_map(answers)

    def v2str(q, v):
        if q.get("type") == "multi":
            return "|".join(v or [])
        return "" if v is None else str(v)

    headers = ["session_id", "user_email", "status", "score", "submitted_at"] + qids
    row = [
        session.get("id",""),
        session.get("user_email",""),
        session.get("status",""),
        session.get("score",""),
        (session.get("submitted_at") or "").replace("T"," ")[:19],
    ] + [ v2str(qs_by_id[qid], amap.get(qid)) for qid in qids ]
    return headers, row

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

def csv_user_sessions(client, user_email: str) -> bytes:
    rows = qexec(
        client.table("survey_sessions")
        .select("id, survey_version_id, status, score, created_at, submitted_at")
        .eq("user_email", user_email)
        .order("created_at", desc=True)
    ) or []

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id","version_id","status","score","created_at","submitted_at"])
    for r in rows:
        w.writerow([r.get("id"), r.get("survey_version_id"), r.get("status"),
                    r.get("score"), r.get("created_at"), r.get("submitted_at")])
    return buf.getvalue().encode("utf-8")

def csv_single_session_answers(client, session_id: str) -> Tuple[str, bytes]:
    session, answers, version = _load_session_with_answers(client, session_id)
    if not session or not version:
        return ("session_answers.csv", b"id,NO_DATA\n")
    qb = _questions_by_id(version)
    # Kolejność według wersji
    qids = list(qb.keys())

    # Mapa odpowiedzi
    amap = {a["question_id"]: a["answer"] for a in answers}

    buf = io.StringIO()
    w = csv.writer(buf)
    header = ["session_id","user_email","status","score","submitted_at"] + qids
    w.writerow(header)

    def _val_to_str(q, val):
        if q.get("type") == "multi":
            return "|".join(val or [])
        return "" if val is None else str(val)

    row = [
        session["id"],
        session.get("user_email",""),
        session.get("status",""),
        session.get("score",""),
        session.get("submitted_at",""),
    ] + [_val_to_str(qb[qid], (amap.get(qid) or {}).get("value")) for qid in qids]

    w.writerow(row)
    fname = f"answers_{session['id']}.csv"
    return (fname, buf.getvalue().encode("utf-8"))

def admin_csv_all_sessions_for_version(client, version_id: str) -> Tuple[bytes, bytes]:
    # sessions summary
    sessions = qexec(
        client.table("survey_sessions")
        .select("id, user_email, status, score, created_at, submitted_at")
        .eq("survey_version_id", version_id)
        .order("created_at")
    ) or []

    buf_s = io.StringIO(); ws = csv.writer(buf_s)
    ws.writerow(["id","user_email","status","score","created_at","submitted_at"])
    for s in sessions:
        ws.writerow([s["id"], s["user_email"], s["status"], s["score"], s["created_at"], s["submitted_at"]])
    sessions_csv = buf_s.getvalue().encode("utf-8")

    # answers wide (kolumny = pytania)
    version = _get_version(client, version_id)
    qb = _questions_by_id(version)
    qids = list(qb.keys())

    # Zbuduj mapę: session_id -> {qid: value}
    answers = qexec(
        client.table("survey_answers")
        .select("session_id, question_id, answer")
        .in_("session_id", [s["id"] for s in sessions] or ["00000000-0000-0000-0000-000000000000"])
    ) or []
    amap: Dict[str, Dict[str, Any]] = {}
    for a in answers:
        sid = a["session_id"]; qid = a["question_id"]; val = (a["answer"] or {}).get("value")
        amap.setdefault(sid, {})[qid] = val

    def _val_to_str(q, val):
        if q.get("type") == "multi":
            return "|".join(val or [])
        return "" if val is None else str(val)

    buf_a = io.StringIO(); wa = csv.writer(buf_a)
    wa.writerow(["session_id","user_email","status","score","submitted_at"] + qids)
    for s in sessions:
        row = [s["id"], s["user_email"], s["status"], s["score"], s["submitted_at"]]
        for qid in qids:
            row.append(_val_to_str(qb[qid], amap.get(s["id"], {}).get(qid)))
        wa.writerow(row)
    answers_csv = buf_a.getvalue().encode("utf-8")

    return sessions_csv, answers_csv

def _build_pdf_for_session(version: Dict[str, Any],
                           session: Dict[str, Any],
                           answers: List[Dict[str, Any]],
                           thr_g: int, thr_a: int) -> bytes:
    """
    Szybki PDF przez reportlab (bez wkhtml/Weasy). Prosty układ: nagłówek, metadane, wynik, lista Q/A.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        from reportlab.lib.enums import TA_LEFT
    except Exception as e:
        # Gdyby brakowało biblioteki, zwróć „fałszywy PDF” z podpowiedzią.
        return f"Reportlab not available: {e}".encode("utf-8")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18*mm, rightMargin=18*mm,
                            topMargin=18*mm, bottomMargin=18*mm)
    styles = getSampleStyleSheet()
    styleH = styles["Heading1"]; styleH.alignment = TA_LEFT
    styleP = styles["BodyText"]

    flow = []
    title = f"DORA Audit — Sesja {session.get('id','')[:8]}"
    flow.append(Paragraph(title, styleH))
    flow.append(Spacer(1, 6))

    # Metadane
    md = [
        ["Użytkownik", session.get("user_email","")],
        ["Status", session.get("status","")],
        ["Wersja", f"v{version.get('version','')}"],
        ["Wysłano", (session.get("submitted_at") or "").replace("T"," ")[:19]],
    ]
    t_md = Table(md, hAlign="LEFT", colWidths=[40*mm, 110*mm])
    t_md.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
        ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
        ("ALIGN",(0,0),(-1,-1),"LEFT"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]))
    flow.append(t_md)
    flow.append(Spacer(1, 8))

    # Wynik + badge
    score = session.get("score")
    if score is not None:
        label, color = _result_badge(float(score), thr_g, thr_a)
        # prosta „łatka” z kolorem
        flow.append(Paragraph(f"Wynik: <b>{score:g}</b> — {label}", styleP))
        flow.append(Spacer(1, 6))

    # Tabela pytań i odpowiedzi
    qs_by_id = _questions_by_id(version)
    amap = _answers_map(answers)
    rows = [["#", "Pytanie", "Odpowiedź", "Punkty"]]
    idx = 1
    for qid, q in qs_by_id.items():
        val = amap.get(qid)
        txt = ""
        if q.get("type") == "multi":
            txt = ", ".join(val or [])
        else:
            txt = "" if val in (None,"") else str(val)
        # „punkty” jeśli liczysz per pytanie
        try:
            pts = _score_answer(q, val)
        except Exception:
            pts = ""
        rows.append([idx, q.get("text",""), txt, pts])
        idx += 1

    t = Table(rows, repeatRows=1, colWidths=[10*mm, 90*mm, 60*mm, 20*mm])
    t.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
        ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    flow.append(t)

    doc.build(flow)
    return buf.getvalue()

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
            st.button("➕ Rozpocznij nową ankietę", type="primary", use_container_width=True):
                st.session_state.pop("resume_session_id", None)
                render_take_survey(client=supa(), user_email=current_email)
                st.stop()
        with c2:
            st.button("⤴️ Wróć do ostatniej ankiety", use_container_width=True)

        render_my_attempts(supa(), current_email)

        # jeśli ktoś kliknął "Wznów"
        if st.session_state.get("resume_session_id"):
            render_take_survey(supa(), current_email, session_id=st.session_state["resume_session_id"])
            st.stop()
    else:
        ui_card("Brak aktywnej wersji ankiety", "<p class='muted'>Skontaktuj się z administratorem.</p>")

def _result_badge(score: float, thr_green: int, thr_amber: int) -> Tuple[str, str]:
    """
    Zwraca (label, color) dla wyniku.
    green: score >= thr_green
    amber: score >= thr_amber
    red:   w pozostałych przypadkach
    """
    if score >= thr_green:
        return ("Green", "#2ecc71")
    if score >= thr_amber:
        return ("Amber", "#f1c40f")
    return ("Red", "#e74c3c")

def _load_draft_answers(client, session_id: str) -> Dict[str, Any]:
    ans = qexec(
        client.table("survey_answers")
        .select("question_id, answer")
        .eq("session_id", session_id)
    )
    return {row["question_id"]: row["answer"] for row in ans}

def _compute_total_score(questions: List[Dict[str, Any]], filled: Dict[str, Any]) -> float:
    total = 0.0
    for q in questions:
        qid = q.get("id")
        payload = filled.get(qid)
        if not payload:
            continue
        total += _score_answer(q, payload.get("value"))
    return total

def render_take_survey(client: Client, user_email: str, session_id: Optional[str] = None):
    """
    - bez session_id: tworzy nową sesję DRAFT przy 'Zapisz szkic' albo SUBMITTED przy 'Wyślij' (jak poprzednio),
    - z session_id: wznawia; pre-fill z survey_answers; można zapisać szkic lub wysłać.
    """
    active = _load_active_version(client)
    ui.header("Wypełnij ankietę")

    if not active:
        with ui.card("Brak aktywnej wersji"):
            st.write("Administrator nie ustawił aktywnej wersji.")
        return

    content = active.get("content") or {}
    title = content.get("title", "DORA Audit")
    questions: List[Dict[str, Any]] = content.get("questions", [])
    thr_green = int(active.get("threshold_green", 80))
    thr_amber = int(active.get("threshold_amber", 60))

    # Jeżeli wznawiamy szkic – pobierz i pre-fill
    prefill: Dict[str, Any] = {}
    if session_id:
        prefill = _load_draft_answers(client, session_id)

    with ui.card(title):
        st.write(f"**Wersja**: {active.get('version')}  •  **Progi**: GREEN ≥ {thr_green}, AMBER ≥ {thr_amber}")
        if session_id:
            st.info(f"Wznawiasz szkic: `{session_id}`")

    with st.form(key=f"survey_form_{session_id or 'new'}"):
        answers_payload: Dict[str, Any] = {}

        for idx, q in enumerate(questions, start=1):
            qid   = q.get("id") or f"q{idx}"
            qtype = q.get("type")
            qtext = q.get("text", f"Pytanie {idx}")
            st.markdown(f"**{idx}. {qtext}**")

            saved = prefill.get(qid, {})
            default_val = saved.get("value")

            if qtype == "single":
                labels = [opt.get("label") for opt in q.get("options", [])]
                val = st.radio(
                    label="",
                    options=labels,
                    index=(labels.index(default_val) if default_val in labels else 0) if labels else None,
                    key=f"q_single_{qid}"
                )
                answers_payload[qid] = {"type": "single", "value": val}

            elif qtype == "multi":
                labels = [opt.get("label") for opt in q.get("options", [])]
                def_list = [v for v in (default_val or []) if v in labels]
                val = st.multiselect(
                    label="",
                    options=labels,
                    default=def_list,
                    key=f"q_multi_{qid}"
                )
                answers_payload[qid] = {"type": "multi", "value": val}

            elif qtype == "scale":
                mn = int(q.get("min", 1))
                mx = int(q.get("max", 5))
                step = int(q.get("step", 1))
                labels = q.get("labels", {})
                def_val = int(default_val) if isinstance(default_val, (int, float)) and mn <= int(default_val) <= mx else mn
                val = st.slider(
                    label=labels.get(str(mn), "") + " ← " + labels.get(str(mx), ""),
                    min_value=mn, max_value=mx, step=step,
                    value=def_val,
                    key=f"q_scale_{qid}"
                )
                answers_payload[qid] = {"type": "scale", "value": val}

            elif qtype == "text":
                val = st.text_area("", value=(default_val or ""), key=f"q_text_{qid}")
                answers_payload[qid] = {"type": "text", "value": val}
            else:
                st.info(f"(pominięto nieznany typ `{qtype}`)")

            st.divider()

        c1, c2 = st.columns([0.5, 0.5])
        save_draft = c1.form_submit_button("Zapisz szkic", use_container_width=True)
        submitted  = c2.form_submit_button("Wyślij ankietę", type="primary", use_container_width=True)

    # --- zapis szkicu: upsert odpowiedzi + status='draft'
    if save_draft:
        try:
            # jeżeli brak session_id – twórz draft (bez score na siłę; ale policzymy, by user widział podgląd)
            if not session_id:
                ses = qexec(
                    client.table("survey_sessions").insert({
                        "survey_version_id": active["id"],
                        "user_email": user_email,
                        "status": "draft",
                        "score": _compute_total_score(questions, answers_payload),
                    }).select("*").single()
                )
                session_id = ses["id"]
            else:
                # aktualizuj sesję (draft)
                qexec(
                    client.table("survey_sessions")
                    .update({"status": "draft", "score": _compute_total_score(questions, answers_payload)})
                    .eq("id", session_id)
                )

            # upsert odpowiedzi (unikat: session_id + question_id)
            upsert_rows = []
            for q in questions:
                qid = q.get("id")
                upsert_rows.append({
                    "session_id": session_id,
                    "question_id": qid,
                    "answer": answers_payload.get(qid, {"type": q.get("type"), "value": None})
                })
            if upsert_rows:
                qexec(
                    client.table("survey_answers")
                    .upsert(upsert_rows, on_conflict="session_id,question_id")
                )

            with ui.card("Szkic zapisany"):
                st.success("Możesz wrócić do szkicu w sekcji **Moje podejścia**.")
            st.session_state["resume_session_id"] = session_id
        except Exception as e:
            with ui.card("Błąd zapisu szkicu"):
                st.error(str(e))
        return

    # --- submit: finalny zapis (status submitted), przelicz wynik, dopisz submitted_at
    if submitted:
        try:
            total_score = _compute_total_score(questions, answers_payload)

            if not session_id:
                ses = qexec(
                    client.table("survey_sessions").insert({
                        "survey_version_id": active["id"],
                        "user_email": user_email,
                        "status": "submitted",
                        "score": total_score,
                        "submitted_at": datetime.utcnow().isoformat() + "Z",
                    }).select("*").single()
                )
                session_id = ses["id"]
            else:
                qexec(
                    client.table("survey_sessions").update({
                        "status": "submitted",
                        "score": total_score,
                        "submitted_at": datetime.utcnow().isoformat() + "Z",
                    }).eq("id", session_id)
                )

            # upsert odpowiedzi (by nadpisać ostatnie zmiany z formularza)
            upsert_rows = []
            for q in questions:
                qid = q.get("id")
                upsert_rows.append({
                    "session_id": session_id,
                    "question_id": qid,
                    "answer": answers_payload.get(qid, {"type": q.get("type"), "value": None})
                })
            if upsert_rows:
                qexec(client.table("survey_answers").upsert(upsert_rows, on_conflict="session_id,question_id"))

            label, color = _result_badge(total_score, thr_green, thr_amber)
            with ui.card("Wynik"):
                st.write(f"**Twój wynik:** {total_score:.0f} pkt")
                st.markdown(
                    f'<div style="display:inline-block;padding:6px 12px;border-radius:8px;background:{color};color:#000;font-weight:700">{label}</div>',
                    unsafe_allow_html=True
                )
                st.success("Odpowiedzi zapisane. Dziękujemy!")
            # po submit możesz wyczyścić znacznik resume:
            st.session_state.pop("resume_session_id", None)
        except Exception as e:
            with ui.card("Błąd wysyłki"):
                st.error(str(e))
        return

def render_session_view(client, session_id: str):
    session, answers, version = _load_session_with_answers(client, session_id)
    if not session:
        with ui.card("Brak sesji"):
            st.error("Nie znaleziono sesji.")
        return

    qb = _questions_by_id(version) if version else {}
    thr_g = int(version.get("threshold_green", 80)) if version else 80
    thr_a = int(version.get("threshold_amber", 60)) if version else 60

    ui.header("Podgląd sesji")
    with ui.card("Informacje"):
        c1, c2, c3, c4 = st.columns([0.3,0.3,0.2,0.2])
        c1.write(f"**Status:** {session['status']}")
        c2.write(f"**Użytkownik:** {session.get('user_email','')}")
        c3.write(f"**Wynik:** {session.get('score') if session.get('score') is not None else '-'}")
        c4.write((session.get("submitted_at") or "").replace("T"," ")[:19])

        if session.get("score") is not None:
            label, color = _result_badge(float(session["score"]), thr_g, thr_a)
            st.markdown(
                f'<div style="display:inline-block;margin-top:6px;padding:6px 12px;border-radius:8px;background:{color};color:#000;font-weight:700">{label}</div>',
                unsafe_allow_html=True
            )

    with ui.card("Odpowiedzi"):
        if not answers:
            st.info("Brak odpowiedzi (pusty szkic).")
            return

        # Mapka odpowiedzi
        ans_map = {a["question_id"]: a["answer"] for a in answers}

        for idx, (qid, q) in enumerate(qb.items(), start=1):
            a = ans_map.get(qid, {})
            val = a.get("value")
            t = q.get("type")
            st.markdown(f"**{idx}. {q.get('text','(pytanie)')}**")
            if t == "multi":
                st.write(", ".join(val or []))
            else:
                st.write(val if val not in (None, "") else "—")

            # Pokaż punktację per pytanie (jeśli liczona)
            try:
                pts = _score_answer(q, val)
                st.caption(f"Punkty: {pts:g}")
            except Exception:
                pass

            st.divider()

        # --- Tabelkowy „pivot” (kolumny = pytania)
    with ui.card("Tabela odpowiedzi (pivot)"):
        if not version:
            st.info("Brak wersji ankiety – nie można zbudować tabeli.")
        else:
            headers, row = _wide_row_for_session(version, session, answers)
            # prosty „DataFrame” bez Pandas – Streamlit łyka listę rekordów:
            records = [dict(zip(headers, row))]
            st.dataframe(records, use_container_width=True, hide_index=True)

    # --- PDF
    with ui.card("Eksport PDF"):
        try:
            pdf_bytes = _build_pdf_for_session(version, session, answers, thr_g, thr_a)
            st.download_button(
                "Pobierz PDF",
                data=pdf_bytes,
                file_name=f"session_{session['id'][:8]}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
        except Exception as e:
            st.warning(f"Nie udało się zbudować PDF: {e}")


def render_my_attempts(client, user_email: str):
    ui.header("Moje podejścia")
    rows = qexec(
        client.table("survey_sessions")
        .select("id, status, score, created_at, submitted_at")
        .eq("user_email", user_email)
        .order("created_at", desc=True)
        .limit(50)
    )

    if not rows:
        with ui.card("Brak podejść"):
            st.write("Nie masz jeszcze żadnych sesji.")
        return

    with ui.card("Lista podejść"):
        for r in rows:
            cols = st.columns([0.5, 0.5, 0.7, 0.7, 0.3, 0.3, 0.3])
            cols[0].write(f"**{r['status']}**")
            cols[1].write(f"score: {r['score'] if r['score'] is not None else '-'}")
            cols[2].write(r.get("created_at", "")[:19].replace("T", " "))
            cols[3].write((r.get("submitted_at") or "")[:19].replace("T", " "))
            if r["status"] == "draft":
                if cols[4].button("Wznów", key=f"resume_{r['id']}"):
                    st.session_state["resume_session_id"] = r["id"]
                    st.rerun()
            else:
                cols[4].write("—")
            # w pętli listy podejść:
            if cols[5].button("Podgląd", key=f"view_{r['id']}"):
                st.session_state["view_session_id"] = r["id"]
                st.rerun()
            # po podglądzie / wznowieniu:
            if r["status"] == "submitted":
                if cols[6].button("CSV", key=f"csv_{r['id']}"):
                    name, data = csv_single_session_answers(supa(), r["id"])
                    st.download_button("Pobierz CSV odpowiedzi", data=data, file_name=name, mime="text/csv")

    view_id = st.session_state.get("view_session_id")
    if view_id:
        render_session_view(supa(), view_id)

    with ui.card("Eksport moich sesji"):
    if st.button("Pobierz listę moich sesji (CSV)"):
        data = csv_user_sessions(supa(), user_email)
        st.download_button("Pobierz sessions.csv", data=data, file_name="my_sessions.csv", mime="text/csv")


import csv, io
from typing import Dict, Any, List, Optional, Tuple

def _get_version(client, version_id: str) -> Optional[Dict[str, Any]]:
    row = qexec(
        client.table("survey_versions")
        .select("*")
        .eq("id", version_id)
        .single()
    )
    return row or None

def _questions_by_id(version: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    content = version.get("content") or {}
    qs = content.get("questions", []) or []
    return {q.get("id") or f"q{idx}": q for idx, q in enumerate(qs, start=1)}

def _load_session_with_answers(client, session_id: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Zwraca: (session, answers[], version)"""
    session = qexec(
        client.table("survey_sessions")
        .select("*")
        .eq("id", session_id)
        .single()
    )
    if not session:
        return None, [], None
    answers = qexec(
        client.table("survey_answers")
        .select("question_id, answer")
        .eq("session_id", session_id)
        .order("question_id")
    ) or []
    version = _get_version(client, session["survey_version_id"])
    return session, answers, version


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

def _whitelist_all(client: Client) -> List[Dict[str, Any]]:
    return qexec(
        client.table("allowed_emails")
              .select("email, created_at, source, is_admin")
              .order("created_at", desc=True)
    )

def _whitelist_add_user(client: Client, email: str) -> None:
    email = email.strip().lower()
    # upsert – jeżeli rekord istnieje, nie popsuj flagi admina
    qexec(
        client.table("allowed_emails").upsert(
            {"email": email, "source": "admin"},
            on_conflict="email"
        )
    )

def _whitelist_add_admin(client: Client, email: str) -> None:
    email = email.strip().lower()
    qexec(
        client.table("allowed_emails").upsert(
            {"email": email, "source": "admin", "is_admin": True},
            on_conflict="email"
        )
    )

def _whitelist_remove_admin(client: Client, email: str) -> None:
    email = email.strip().lower()
    qexec(
        client.table("allowed_emails")
              .update({"is_admin": False})
              .eq("email", email)
    )

def render_admin_whitelist_block(client: Client):
    st.subheader("Whitelist / Administratorzy")

    new_email = st.text_input("Dodaj adres e-mail", placeholder="user@firma.com")
    col1, col2, col3 = st.columns([1,1,1])

    with col1:
        if st.button("Dodaj do whitelisty (user)", type="secondary", disabled=not new_email):
            try:
                _whitelist_add_user(client, new_email)
                st.success(f"Dodano do whitelisty: {new_email}")
            except Exception as e:
                st.error(str(e))

    with col2:
        if st.button("Dodaj jako administratora", type="secondary", disabled=not new_email):
            try:
                _whitelist_add_admin(client, new_email)
                st.success(f"Nadano uprawnienia admin: {new_email}")
            except Exception as e:
                st.error(str(e))

    with col3:
        if st.button("Usuń uprawnienia admin", type="secondary", disabled=not new_email):
            try:
                _whitelist_remove_admin(client, new_email)
                st.success(f"Usunięto uprawnienia admin: {new_email}")
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.caption("Lista dozwolonych adresów")
    try:
        rows = _whitelist_all(client)
        st.dataframe(rows, use_container_width=True)
    except Exception as e:
        st.error(str(e))

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

    with ui.card("Eksport (Admin)"):
    versions = qexec(
        client.table("survey_versions")
        .select("id, version, is_active, created_at")
        .order("created_at", desc=True)
        .limit(100)
    ) or []

    if not versions:
        st.info("Brak wersji.")
    else:
        lbls = [f"v{v['version']} ({'active' if v['is_active'] else v['created_at'][:10]})" for v in versions]
        chosen = st.selectbox("Wybierz wersję do eksportu", options=list(range(len(versions))), format_func=lambda i: lbls[i])
        ver_id = versions[chosen]["id"]

        c1, c2 = st.columns([0.5,0.5])
        if c1.button("Pobierz sessions.csv"):
            s_csv, _ = admin_csv_all_sessions_for_version(client, ver_id)
            st.download_button("Pobierz sessions.csv", data=s_csv, file_name=f"sessions_{versions[chosen]['version']}.csv", mime="text/csv")

        if c2.button("Pobierz answers_wide.csv"):
            _, a_csv = admin_csv_all_sessions_for_version(client, ver_id)
            st.download_button("Pobierz answers_wide.csv", data=a_csv, file_name=f"answers_wide_{versions[chosen]['version']}.csv", mime="text/csv")

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
