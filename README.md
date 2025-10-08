# DORA Audit — Full Repo (with full CI/security)

- Streamlit app with `hint/Podpowiedź` support
- Static site (PL/EN), dark theme
- Supabase SQL (assessments, access_codes)
- Unit tests + E2E scaffolding
- Workflows: GH Pages, Pytest, E2E, GHCR publish, Semantic Release, Pre-release/Release, Trivy (strict), Snyk, CodeQL, License Scan, Release Drafter, Dependabot

## Local (Docker Compose)
docker compose up --build
# app  -> http://localhost:8501
# site -> http://localhost:8080

## Local (Python)
cd app && python -m venv .venv && source .venv/bin/activate  # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt && streamlit run app.py

## Tests
pip install -r requirements-dev.txt && pytest -q

# 🧭 DORA Audit — Full Repository (App + Site + CI/CD + Security)

Kompletny zestaw do uruchomienia, testowania i automatycznego publikowania aplikacji **DORA Audit** — z pełnym łańcuchem CI/CD, automatycznymi skanami bezpieczeństwa, analizą kodu oraz publikacją obrazu Dockera w GHCR.

---

## 🔧 1. Wymagane narzędzia

- **Git** → [https://git-scm.com/downloads](https://git-scm.com/downloads)
- **Python 3.11+** → [https://www.python.org/downloads/](https://www.python.org/downloads/)
- **Docker Desktop** → [https://www.docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)
- **Node.js (v20)** → [https://nodejs.org/en/download](https://nodejs.org/en/download)
- *(opcjonalnie)* **VS Code** z pluginami: *Docker*, *GitHub Actions*, *YAML*, *Markdown All in One*

---

## 💾 2. Utworzenie repozytorium GitHub

1. Wejdź na [https://github.com/new](https://github.com/new)
2. Utwórz repozytorium o nazwie np. `dora-audit`
3. Nie dodawaj README – wkleimy gotowy plik
4. Kliknij **Create repository**

---

## 📦 3. Załadowanie projektu

1. Pobierz paczkę ZIP `dora_full_repo_with_ci.zip`
2. Rozpakuj ją lokalnie (np. `~/Projects/dora-audit`)
3. W terminalu:

```bash
cd ~/Projects/dora-audit
git init
git remote add origin https://github.com/<TwojaNazwaUżytkownika>/dora-audit.git
git add .
git commit -m "Initial commit — full repo with CI/CD and security workflows"
git branch -M main
git push -u origin main
