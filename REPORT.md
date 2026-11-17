# Ask the Archive — rapport

David Pretty · `compass-challenge-david-pretty` · score sur les 20 exemples : **45,00 / 45**

## 1. Vue d'ensemble

**Problème.** 3 048 PDF fictifs de Brumeval (≈ 2 M tokens, deux fois le
contexte du modèle), en français et en anglais, avec coquilles, tableaux et
versions successives. Il faut répondre court, citer les documents, et dire
`not_found` ou `conflict` quand il le faut, en moins de 20 min pour 60
questions, sur CPU.

**Approche : RAG hybride + recettes déterministes + validation en Python.**

```
question ─► routeur (regex + 1 appel LLM de plan) ─► recette
             direct · agrégation · version en vigueur · multi-sauts
         ─► recherche hybride (BM25 + dense, fusion RRF, filtres d'identifiants)
         ─► brouillon structuré (1 appel LLM, JSON validé par pydantic)
         ─► validation + ancrage en Python ─► answers.jsonl + trace JSON
```

**Stack.** Python 3.11, pdfplumber (texte et tableaux), Qdrant embarqué
(index pré-construit et versionné, synchronisé au démarrage par un manifeste
taille + SHA-1 : seuls les PDF ajoutés ou modifiés sont réindexés), fastembed
(BM25 et MiniLM multilingue en ONNX, sans PyTorch), SDK `openai`, pydantic.
Aucun serveur, aucun GPU.

**Gestion des erreurs.** Variable `LLM_*` manquante, corpus ou fichier
introuvable : message explicite et code 1. API : timeouts, 429 et 5xx rejoués
avec backoff (3 tentatives, `Retry-After` respecté). Sortie mal formée :
schéma JSON, puis JSON dans le texte, puis une demande de réparation. Budgets
de 60 s par question et 17 min au total : toute question en échec reçoit une
ligne `not_found`, le fichier contient toujours une ligne par id. Modèle
dense indisponible : repli BM25 seul.

**Traçabilité.** Une citation n'est gardée que si le document a été récupéré
pour cette question. Chaque preuve est une citation mot pour mot, vérifiée en
Python dans le texte du document ; chaque valeur de la réponse doit figurer
dans une citation vérifiée ou dans un calcul fait en Python. Le résultat donne
un niveau de confiance par règles (élevée, moyenne, faible) et une trace JSON
par question, que l'angle libre rend lisible.

## 2. Compromis et résultats

| Décision | Alternatives écartées | Pourquoi |
|---|---|---|
| Index pré-construit, Qdrant embarqué hybride | Extraction au lancement ; serveur Qdrant ou Elasticsearch | L'extraction prend ≈ 0,17 s/doc (≈ 9 min) ; installation `pip` seule exigée, donc pas de Docker |
| pdfplumber, tableaux rendus en lignes `cellule \| cellule` | markitdown, PyMuPDF, docling | markitdown ne repère pas les tableaux, PyMuPDF est AGPL, docling demande torch et est lent |
| Recettes déterministes + un seul appel de brouillon | Agent ReAct à outils libres | Temps et coût prévisibles. L'agrégation liste toutes les factures et somme en décimal exact en Python ; le multi-sauts suit les codes partagés (BRV-, F-, C-) puis le champ `missing` du brouillon (≤ 3 brouillons) |
| Dense MiniLM, sans reranker | e5-large (2,2 Go) ; rerankers jina et bge mesurés | MiniLM est le plus petit modèle à 0,02 du meilleur rappel (rappel@16 : 0,79 → 0,82, +0,07 sur des paraphrases) ; le reranking coûtait 20 à 35 min pour 60 questions sur CPU |
| Ancrage signalé, jamais d'abstention sur échec de validation | Réessai avec retour au modèle, abstention | Une abstention injustifiée coûte la question et 0,17 pt ; on garde la réponse avec une confiance faible |

**Progression du score (20 exemples).**

| Étape | Score | Erreurs restantes |
|---|---|---|
| 01 Squelette BM25, 1 appel | 26,60 | multi-sauts 0/4, agrégation 1/3, versions 1/3 |
| 02 Ingestion : tableaux, métadonnées, versions, top-k | 33,30 | multi-sauts 0/4, agrégation 2/3 |
| 03 Dense + fusion RRF | 33,30 | rappel en hausse, score inchangé |
| 04 Routeur + recettes | 35,64 | multi-sauts 0/4 |
| 05 Multi-sauts + filet de sécurité | 45,00 | aucune |
| 06–07 Ancrage, application web | 45,00 | aucune |

Temps : 5,2 s par question en moyenne (max 13,8 s, 8 en parallèle) ;
démarrage à froid 20 s, téléchargement du modèle dense compris.

**Analyse des erreurs.**

- *Profondeur de recherche.* Deux questions d'agrégation attendent 12 et 17
  documents, plus que les 8 premiers résultats : la somme était partielle. La
  recette liste désormais toutes les factures filtrées (client, projet,
  période), puis somme en Python.
- *Versions.* Sans dates d'effet, rien n'indiquait quelle version d'une
  politique s'appliquait à la date demandée. Les versions ont maintenant des
  dates d'effet extraites, et la recette désigne la version en vigueur.
- *Multi-sauts (0/4).* Une seule passe ne voyait que le premier maillon
  (facture → projet → répertoire). L'expansion par identifiants et le champ
  `missing` ajoutent les maillons suivants.
- *Trouvées en posant de nouvelles questions dans l'application.* (1) « en
  vigueur en 2025 » devenait le 1er janvier, donc la version 2, alors que la
  version 3 s'applique dès le 17 janvier : la règle retient maintenant la
  dernière version en vigueur dans la période. (2) Le modèle ajoutait des
  valeurs annexes (« 0,57 $… 0,53 $ avant cette date »), ce qui peut faire
  compter une bonne réponse comme fausse : le brouillon donne maintenant la
  valeur seule. (3) L'ancrage lisait des morceaux de date comme des montants
  (faux signalements), corrigé.

**Risques acceptés.** Vingt exemples seulement : les recettes peuvent être
trop ajustées. Une question d'agrégation ou de version mal routée n'est pas
rattrapée. Le modèle dense est téléchargé au lancement (repli BM25). Le
stockage Qdrant local est lié aux versions épinglées.

## 3. Angle libre : « vérifier en un clic »

Une réponse accompagnée d'un `doc_id` oblige encore le relecteur à rouvrir
le PDF et à chercher la phrase. L'application locale
(`python scripts/serve.py`, sans dépendance ajoutée) répond à cela :

- **Poser une question en direct.** Les étapes du pipeline s'affichent au fur
  et à mesure (routage, recherche, rédaction, saut, validation, vérification,
  rendu), puis restent sous la réponse avec leur durée.
- **La preuve sur la page.** Chaque citation est encadrée sur l'image de la
  page PDF : verte si elle est vérifiée, rouge si elle est absente du
  document ; la valeur extraite est encadrée en plus foncé.
- **Une confiance expliquée.** « Pourquoi cette confiance ? » liste les règles
  déclenchées. Les valeurs non appuyées sont nommées une à une, par exemple
  « 0,53 $ — introuvable dans les sources ».
- **Les cas difficiles lisibles.** Conflits côte à côte, documents consultés
  pour un `not_found`, historique des questions posées.

Utilité : sur un vrai cas, l'application a montré que le modèle citait la
version 3 tout en ajoutant le taux de la version 2 sans le citer. Elle
distingue « le modèle a oublié de citer » de « la réponse est appuyée », et
désigne les réponses à relire en priorité. La vérification est faite en
Python, sans appel LLM supplémentaire. Le serveur n'écoute que `127.0.0.1` et
refuse les requêtes venant d'un autre site.

**Démo (2 min) :** [LIEN DÉMO]
