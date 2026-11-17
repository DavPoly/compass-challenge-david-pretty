# compass-challenge-david-pretty

Solution au défi « Ask the Archive » — Semaine Info/Log 2026.

## Installation (2 étapes maximum)

Python ≥ 3.11.

1. Créer et activer un environnement virtuel :

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Linux / macOS
   .venv\Scripts\activate           # Windows (cmd ou PowerShell)
   ```

2. Installer les dépendances :

   ```bash
   pip install -r requirements.txt
   ```

## Exécution

```bash
export LLM_BASE_URL=...   # API compatible OpenAI, fournie par l'organisation
export LLM_API_KEY=...
export LLM_MODEL=...
python answer.py questions.jsonl answers.jsonl
```

(Windows PowerShell : `$env:LLM_BASE_URL = "..."`, etc.)

Exemple de sortie : `answers.jsonl`, une ligne par question, par exemple
`{"id": "s01", "answer": "30", "citations": ["doc_0042"], "status": "answered"}`.
`status` vaut `answered`, `not_found` ou `conflict`.

Points à connaître :

- **Index prêt à l'emploi** : l'index (Qdrant embarqué) est construit et
  versionné dans `index/`. Aucune étape d'indexation manuelle.
- **Nouveaux PDF** : au démarrage, `corpus/` est comparé au manifeste de
  l'index (taille, puis SHA-1). Seuls les documents ajoutés, modifiés ou
  supprimés sont réindexés. Un échec de synchronisation est journalisé et
  l'index existant est utilisé.
- **Modèle dense** : le modèle d'embedding multilingue est téléchargé au
  premier lancement (cache dans `.cache/models/`). S'il ne peut pas être
  chargé, la recherche bascule sur BM25 seul.
- **Budgets** : 60 s par question, échéance globale de 17 min, 8 threads.
  Une question en échec, hors budget ou non traitée à l'échéance reçoit une
  ligne `not_found` ; `answers.jsonl` contient toujours une ligne par id.
- Le détail du déroulement est journalisé sur stderr.

## Messages d'erreur

Les erreurs vont sur stderr ; les messages `ERROR` du pipeline sont préfixés
par la date et le logger (omis ci-dessous). Code de sortie 0 : exécution
terminée (même avec des `not_found`).

| Situation | Code | Message affiché |
|---|---|---|
| `LLM_BASE_URL`, `LLM_API_KEY` ou `LLM_MODEL` manquant ou vide | 1 | `Error: Missing environment variables: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL. Set them before running (export LLM_BASE_URL=...; export LLM_API_KEY=...; export LLM_MODEL=...).` (seules les variables absentes sont listées) |
| `corpus/` absent ou sans PDF | 1 | `No PDF found in corpus directory <repo>/corpus. Run the command from the repo root and put the PDFs in corpus/.` |
| fichier de questions introuvable | 1 | `Cannot read questions file <chemin>: No such file or directory. Pass the path of an existing questions.jsonl.` |
| mauvais nombre d'arguments | 2 | `usage: python answer.py questions.jsonl answers.jsonl` |
| index illisible | 1 | `Cannot open the index at <repo>/index: <raison>` |
| fichier de sortie non inscriptible | 1 | `I/O error while answering <chemin>: <raison>` |

La vérification de `corpus/` passe avant celle du fichier de questions.

Erreurs de l'API LLM : une erreur temporaire (timeout, 429, 408, 409, 5xx)
est rejouée avec un backoff exponentiel (3 tentatives, `Retry-After`
respecté). Si l'API reste indisponible, ou si la clé, le modèle ou l'URL sont
refusés, la question est journalisée (avec un indice : vérifier
`LLM_API_KEY`, `LLM_MODEL` ou `LLM_BASE_URL`) et reçoit `not_found`.

## Bibliothèques utilisées

Versions épinglées dans `requirements.txt` :

- `fastembed==0.9.1` — embeddings denses (MiniLM multilingue, ONNX) et
  vecteurs creux BM25, sans PyTorch.
- `onnxruntime==1.32.0` — moteur d'inférence des modèles de fastembed.
- `openai==3.51.0` — client de l'API compatible OpenAI (`LLM_BASE_URL`).
- `pdfplumber==0.11.10` — extraction du texte et des tableaux des PDF.
- `pydantic==2.14.3` — schémas et validation des réponses du modèle.
- `qdrant-client==1.20.0` — index hybride dense + BM25, embarqué (sans
  serveur).

## Tests et qualité

```bash
pip install -r requirements-dev.txt
ruff check .
mypy --strict archive scripts answer.py
pytest -q
```

## Architecture choisie en 3 lignes

1. **Ingestion** (`archive/ingest`) : pdfplumber, tableaux découpés en chunks
   à part, métadonnées (type de document, dates, versions, identifiants) ;
   index committé et synchronisé de façon incrémentale.
2. **Agent** (`archive/agent`, `archive/retrieval`, `archive/llm`) : routeur
   regex + un appel LLM de planification ; recettes (direct, agrégation avec
   sommes décimales exactes, versions remplacées) ; multi-sauts par expansion
   déterministe des identifiants et boucle de brouillons pilotée par le champ
   `missing` (≤ 3 brouillons) ; filet de sécurité pour les questions directes.
3. **Validation** (`archive/validation`) : schémas pydantic, nouvelle demande
   de réparation au modèle si la sortie est invalide, citations limitées aux
   documents récupérés, règles de statut (`answered` / `not_found` /
   `conflict`).

## Angle libre

À compléter après l'étape 07 : traces et visualiseur.

## Démo (lien)

À compléter après l'étape 07 : traces et visualiseur.

Les détails (choix, mesures, limites) sont dans `REPORT.pdf`.
