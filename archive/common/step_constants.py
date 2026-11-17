"""Constants of the pipeline step events."""

LOG_STEP_CALLBACK_FAILED = "step callback failed for %s; ignored"
EXTRACTS_DETAIL = "{count} extraits"
RECIPE_DETAIL = "{count} extraits ({recipe})"
DRAFT_DETAIL = "brouillon {number}"
FIRST_DRAFT_NUMBER = 1

STEP_LABELS = {
    "route": "Routage de la question",
    "retrieve": "Recherche dans les archives",
    "draft": "Rédaction de la réponse",
    "hop": "Recherche complémentaire",
    "validate": "Validation du format et des citations",
    "ground": "Vérification des citations",
    "render": "Rendu des pages sources",
}

FAMILY_LABELS = {
    "direct": "question directe",
    "multi_hop": "multi-sauts",
    "aggregation": "agrégation",
    "superseded": "version en vigueur",
}
STATUS_LABELS = {
    "answered": "répondue",
    "not_found": "introuvable",
    "conflict": "conflit",
}
CONFIDENCE_LABELS = {
    "high": "confiance élevée",
    "medium": "confiance moyenne",
    "low": "confiance faible",
}
# Raw step detail code -> French wording; unknown codes stay as they are.
DETAIL_LABELS = {**FAMILY_LABELS, **STATUS_LABELS, **CONFIDENCE_LABELS}
