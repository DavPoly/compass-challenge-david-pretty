# Ask the Archive — rapport

David Pretty · `compass-challenge-david-pretty` · score sur les 20 exemples : **45,00 / 45**

## 1. Vue d'ensemble

**Problème.** 3 048 PDF fictifs de Brumeval (≈ 2 M tokens, deux fois le
contexte du modèle), en français et en anglais, avec coquilles, tableaux et
versions successives. Il faut répondre court, citer les documents, et dire
`not_found` ou `conflict` quand il le faut, en moins de 20 min pour 60
questions, sur CPU.

**Approche : Model de routage qui dirige vers des pipelines déterministes par categorie, RAG hybride et validation en Python.**

![Architecture d'« Ask the Archive »](public/architecture_diagram.jpg)

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

**Traçabilité et observabilité.**

- *Citations contrôlées.* Une citation n'est acceptée que si le document fait
  partie des résultats de recherche RAG de la question.
- *Réponse ancrée.* Pour chaque source, le modèle donne un extrait mot pour
  mot ; Python vérifie que l'extrait figure bien dans le document. Chaque
  valeur de la réponse (montant, date, nombre) doit se trouver dans un extrait
  vérifié ou venir d'un calcul fait en Python. Un écart ne bloque pas la
  réponse : il abaisse le niveau de confiance (élevée, moyenne, faible),
  calculé par règles fixes.
- *Une trace par question.* Un fichier JSON (`traces/<run>/`) enregistre le
  plan du routeur, les documents récupérés et leur score, le brouillon, les
  problèmes de validation, les citations écartées, le résultat de l'ancrage,
  la réponse finale et la durée de chaque étape. Le déroulement est aussi
  journalisé sur stderr.
- *Lisible sans ouvrir le JSON.* L'application de l'angle libre (section 3)
  affiche ces étapes en direct et encadre chaque preuve sur la page PDF.

## 2. Compromis et résultats

| Décision | Alternatives écartées | Pourquoi |
|---|---|---|
| Index pré-construit, Qdrant embarqué hybride | Extraction au lancement ; serveur Qdrant ou Elasticsearch | L'extraction prend ≈ 0,17 s/doc (≈ 9 min) ; installation `pip` seule exigée, donc pas de Docker |
| Aucun chunking : un document = une entrée d'index | Séparation des tableaux, et division de la partie texte selon les sections des documents | Le plus long PDF fait 644 mots : chaque document tient entier dans le prompt. Découper aurait séparé un tableau de son en-tête (montant d'une facture sans son client) et occupé plusieurs places du top-k avec le même document. La citation attendue est un `doc_id`, donc un document entier est la bonne unité |
| Routage par le même LLM (1 appel, plan structuré) | Petit modèle de classification, entraîné ou modèle de décision comme JEV | Un classifieur serait plus rapide, moins cher et stable d'un appel à l'autre. Faute de temps et de données d'entraînement (20 exemples), le LLM fourni fait aussi le routage ; des règles regex passent avant lui |
| Pas d'étape de validation de la question | Filtre d'entrée (hors sujet, question vide de sens) | Par simplicité, et à cause de l'existence du routeur qui bloque toute question absurde en `not_found` |
| Pipelines déterministes + un seul appel de brouillon | Agent ReAct à outils libres | Temps et coût prévisibles. L'agrégation liste toutes les factures et somme en décimal exact en Python ; le multi-sauts suit les codes partagés (BRV-, F-, C-) puis le champ `missing` du brouillon (≤ 3 brouillons) |
| Dense MiniLM, sur les 128 premiers tokens | e5-large (2,2 Go) ; fenêtre plus longue | MiniLM est le plus petit modèle à 0,02 du meilleur rappel (rappel@16 : 0,79 → 0,82, +0,07 sur des paraphrases). Seul le début de chaque document est vectorisé ; le document entier aurait été préférable, mais l'indexation et les requêtes sur CPU local dépassaient le budget. BM25 couvre le texte complet |
| Top-k 16 après fusion RRF, sans reranker | Reranker (jina, bge) sur les 30 meilleurs candidats | BM25 et dense renvoient chacun 50 candidats, fusionnés par RRF ; les 16 premiers documents vont au prompt. Avec 8, les agrégations perdaient des factures ; 16 garde le prompt court. Un reranker aurait aidé ici (paraphrases, questions FR sur documents EN, ordre des versions), mais il coûtait 20 à 35 s par question (jina, 11,8 Go de RAM) et 105 à 140 s (bge) sur CPU, hors du budget de 20 min |

**Progression du score et analyse des erreurs (20 exemples).**
D'abord un squelette complet et naïf (recherche BM25, un appel
LLM, validation du format), pour obtenir un score de référence. Ensuite, à
chaque étape : lancer les 20 exemples, lire `score.py --details` par famille
de questions (direct, multi-sauts, agrégation, versions, conflit, sans
réponse), classer chaque échec selon sa cause (document non trouvé, logique
absente, sortie du modèle), puis corriger la cause qui coûte le plus de
points. Une étape n'est gardée que si le score ne baisse pas.

| Étape | Score | Erreurs observées sur les 20 questions | Ce qui a motivé l'étape suivante |
|---|---|---|---|
| 01 Squelette : BM25, top-8, 1 appel | 26,60 | 10 `not_found`, dont 7 injustifiés. Versions 1/3 : rien n'indique quelle version est en vigueur. Multi-sauts 0/4 | La cause principale est la recherche, pas la rédaction |
| 02 Ingestion : tableaux, type de document, dates d'effet, top-16 | 33,30 | Versions 2/3, agrégation 2/3 (s20 : 17 factures, somme toujours partielle), multi-sauts 1/4 (le 2e maillon n'est jamais récupéré). 5 `not_found` injustifiés | Rappel BM25@16 de 0,79, faible sur les paraphrases et les questions FR sur documents EN |
| 03 Dense MiniLM + fusion RRF | 33,30 | Rappel 0,79 → 0,82 (paraphrases 0,80 → 0,87), versions 3/3. Les 5 échecs restants (s20, s04, s05, s08, s15) ne viennent plus de la recherche : il manque de la logique | Traiter chaque famille par un pipeline dédié |
| 04 Routeur + pipelines | 33,14 → 35,64 | Régression : s11 (« heures facturées ») routée en agrégation, le pipeline sommait des montants ; corrigé en réservant l'agrégation aux montants. Multi-sauts 0/4 : une passe ne voit que le premier maillon (facture → projet → répertoire) | Suivre les maillons |
| 05 Multi-sauts + filet de sécurité | 37,98 → 42,51 → 45,00 | Expansion des codes : 1/4, la boucle ne se relançait pas car le brouillon se disait complet en répondant `not_found`. Prompt « chaîne partielle » : 3/4 (s04 citations incomplètes, s08 `not_found`). Citation de toute la chaîne : 4/4 | Plus d'erreur ; rendre chaque réponse vérifiable |
| 06–07 Ancrage, application web | 45,00 | Aucune ; l'ancrage signale sans jamais abstenir, donc pas de régression | — |

Temps : 5,2 s par question en moyenne (max 13,8 s, 8 en parallèle) ;
démarrage à froid 20 s, téléchargement du modèle dense compris.

**Risques acceptés.** Vingt exemples seulement : les pipelines peuvent être
trop ajustées. Une question d'agrégation ou de version mal routée n'est pas
rattrapée. Le modèle dense est téléchargé au lancement (repli BM25). Le
stockage Qdrant local est lié aux versions épinglées.

## 3. Angle libre : « vérifier en un clic »

**Contexte.** Le score sur 20 exemples mesure le système, pas chaque
réponse. En usage réel, il n'y a pas de
corrigé : il faut pouvoir juger une réponse seule.

**Limites du RAG, et ce que l'application montre pour chacune.**

| Limite | Conséquence | Dans l'application |
|---|---|---|
| Une citation est un identifiant, pas une preuve | Le relecteur doit rouvrir le PDF et chercher la phrase | L'extrait est encadré sur l'image de la page PDF : vert s'il figure mot pour mot dans le document |
| Le modèle peut citer un document et prendre la valeur ailleurs | Réponse plausible, citée, mais non appuyée | Chaque valeur non retrouvée est nommée, par exemple « 0,53 $ - introuvable dans les sources » |
| Une confiance donnée par le modèle n'est pas fiable | On ne sait pas quelles réponses relire | Confiance calculée par règles, et « Pourquoi cette confiance ? » liste les règles déclenchées |
| La recherche peut manquer le bon document | Un `not_found` ne dit pas si le document existe | Les documents consultés sont listés avec leur score |
| Versions et sources contradictoires | Le relecteur ne voit qu'une valeur | Les sources en conflit sont affichées côte à côte |
| Le pipeline est une boîte noire | Impossible de savoir quelle étape a échoué | Les étapes s'affichent en direct (routage, recherche, rédaction, saut, validation, vérification), puis restent sous la réponse avec leur durée |

**Limites de l'angle libre.** La vérification est lexicale : un extrait
vérifié prouve que la phrase existe dans le document, pas qu'elle répond à
la question. Elle est faite en Python, sans appel LLM supplémentaire.
L'application (`python scripts/serve.py`, sans dépendance ajoutée) traite une
question à la fois, n'écoute que `127.0.0.1` et refuse les requêtes venant
d'un autre site.

**Démo (2 min) :** [\[DÉMO\]](https://youtu.be/lkWiLNiX0Ww)
