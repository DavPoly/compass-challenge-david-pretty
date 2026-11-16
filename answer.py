#!/usr/bin/env python3
"""Point d'entrée de votre solution.

Commande (toujours la même, lancée depuis la racine de votre repo) :
    python answer.py questions.jsonl answers.jsonl

Entrée  : questions.jsonl, une ligne JSON par question : {"id": "q17", "question": "..."}
Sortie  : answers.jsonl, une ligne JSON par question :
          {"id": "q17", "answer": "30 jours", "citations": ["doc_042"], "status": "answered"}
          status vaut "answered", "not_found" (information absente du corpus)
          ou "conflict" (les sources se contredisent ; citez-les toutes).
Corpus  : lu dans ./corpus/ (doc_0001.pdf, doc_0002.pdf, ... ; l'identifiant est le nom du fichier sans .pdf).

Accès au modèle : seulement par les trois variables d'environnement ci-dessous.
N'écrivez jamais de clé ni de nom de modèle en dur dans le code.

Ce squelette répond "not_found" partout, pour que score.py fonctionne tout de suite.
À vous de le remplacer par votre architecture.
"""
import json
import os
import sys
from pathlib import Path

CORPUS_DIR = Path("corpus")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage : python answer.py questions.jsonl answers.jsonl", file=sys.stderr)
        return 2
    questions_path, answers_path = sys.argv[1], sys.argv[2]

    # Fournies par l'environnement lors de l'évaluation (format « chat completions »).
    llm_base_url = os.environ.get("LLM_BASE_URL")
    llm_api_key = os.environ.get("LLM_API_KEY")
    llm_model = os.environ.get("LLM_MODEL")
    missing = [name for name, value in (("LLM_BASE_URL", llm_base_url), ("LLM_API_KEY", llm_api_key),
                                        ("LLM_MODEL", llm_model)) if not value]
    if missing:
        # Le squelette n'appelle pas le modèle : il avertit seulement. Votre système, lui, devrait
        # s'arrêter ici avec un message explicite (code de sortie 1).
        print(f"Avertissement : variable(s) d'environnement manquante(s) : {', '.join(missing)}. "
              "Exemple : export LLM_MODEL=nom-du-modele", file=sys.stderr)

    if not Path(questions_path).is_file():
        print(f"Erreur : fichier de questions introuvable : {questions_path}", file=sys.stderr)
        return 1
    if not CORPUS_DIR.is_dir():
        print(f"Erreur : dossier du corpus introuvable : {CORPUS_DIR.resolve()} "
              "(lancez la commande depuis la racine du repo)", file=sys.stderr)
        return 1

    try:
        with open(questions_path, encoding="utf-8") as f:
            questions = [json.loads(line) for line in f if line.strip()]
    except json.JSONDecodeError as e:
        print(f"Erreur : {questions_path} n'est pas un JSONL valide (ligne {e.lineno}) : {e.msg}", file=sys.stderr)
        return 1

    with open(answers_path, "w", encoding="utf-8") as out:
        for q in questions:
            answer = {"id": q["id"], "answer": "", "citations": [], "status": "not_found"}
            out.write(json.dumps(answer, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
