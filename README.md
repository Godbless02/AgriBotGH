# AgriBotGH

A bilingual (English–Twi) agricultural chatbot for Ghanaian farmers.

## Project Overview

AgriBotGH is a Flask web application that answers farming questions in English and Twi using a TF-IDF retrieval model and topic-based fallback suggestions.

## Files and Purpose

- `app.py` — Flask backend, AI retrieval logic, and API endpoints.
- `app.js` — frontend chat UI, localStorage session history, and language controls.
- `index.html` — chat application markup.
- `style.css` — UI styling and responsive layout.
- `agri_dataset.json` — local bilingual dataset used by the app.
- `agribotgh_dataset_combined_refined.txt` — raw dataset source.
- `convert_dataset.py` — dataset extraction script from a DOCX source.
- `requirements.txt` — Python dependencies.
- `Procfile` — deployment command for Gunicorn.

## Setup

1. Create and activate a Python virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Optionally set environment variables in a `.env` file or your shell:
   ```bash
   export FLASK_DEBUG=false
   export PORT=5000
   export HF_TOKEN=your_huggingface_token
   ```
4. Run the app:
   ```bash
   python app.py
   ```
5. Open `http://127.0.0.1:5000` in your browser.

## Notes

- The backend prefers the local `agri_dataset.json` dataset and builds TF-IDF models at startup.
- If local dataset files are missing, the app will attempt to download cached assets from Hugging Face.
- If you do not want remote downloads, ensure `agri_dataset.json` is present.

## Improvements Needed

- Add automated tests.
- Add dataset category metadata.
- Remove the committed virtual environment folder (`agribot_env/`).
- Improve dataset validation and translation checks.
