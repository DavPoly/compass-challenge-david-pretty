# compass-challenge-<prénom>-<nom>

Solution au défi « Ask the Archive » — Semaine Info/Log 2026.

## Installation (2 étapes maximum)

```bash
python -m venv .venv && source .venv/bin/activate   # facultatif
pip install -r requirements.txt
```

## Exécution

```bash
export LLM_BASE_URL=...   # fourni par l'organisation
export LLM_API_KEY=...
export LLM_MODEL=...
python answer.py questions.jsonl answers.jsonl
```

Exemple de sortie : `answers.jsonl`, une ligne par question, par exemple
`{"id": "s01", "answer": "30", "citations": ["doc_0042"], "status": "answered"}`.

## Messages d'erreur

| Situation | Message affiché |
|---|---|
| `LLM_API_KEY` ou `LLM_MODEL` manquant | (votre message, ex. « Erreur : variable LLM_MODEL manquante… ») |
| fichier de questions introuvable | … |
| dossier `corpus/` introuvable | … |

## Bibliothèques utilisées

- (liste avec versions, ex. : `rank-bm25==0.2.2` — pourquoi vous l'avez choisie)

## Architecture choisie en 3 lignes

Modules : traitement des documents (…), interaction avec le modèle (…), validation des réponses (…).

1. …
2. …
3. …

## Angle libre

Angle choisi : (interface / UX, petits modèles ou modèles locaux, benchmark de modèles ou de configurations,
confiance et explicabilité, ou autre). En deux ou trois phrases : ce que vous avez fait et ce que ça apporte.
Le détail (une demi-page) est dans `REPORT.pdf`.

## Démo (lien)

Lien vers une capture d'écran ou un enregistrement vidéo de 2 minutes maximum : …

Les détails (choix, mesures, limites) sont dans `REPORT.pdf`.
