
import types
import importlib.util
from pathlib import Path

app_path = Path(__file__).resolve().parents[1] / "app" / "app.py"
spec = importlib.util.spec_from_file_location("app_module", app_path)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

def test_compute_scores_basic():
    import pandas as pd
    df = pd.DataFrame([
        {"section": "SEC1", "question_id": "Q1", "question_text": "A?", "weight": 1.0, "answer": "Yes"},
        {"section": "SEC1", "question_id": "Q2", "question_text": "B?", "weight": 1.0, "answer": "No"},
        {"section": "SEC2", "question_id": "Q3", "question_text": "C?", "weight": 2.0, "answer": "Partial"},
        {"section": "SEC2", "question_id": "Q4", "question_text": "D?", "weight": 1.0, "answer": "N.A."},
    ])
    assert hasattr(app, "compute_scores"), "compute_scores() not found in app.py"
    result = app.compute_scores(df, weights_map={"Yes":1.0,"Partial":0.5,"No":0.0,"N.A.":None})
    assert "total" in result and "by_section" in result
    assert 0.0 <= result["total"] <= 100.0
    assert set(result["by_section"].keys()) == {"SEC1","SEC2"}
