"""Constantes partagées par plusieurs modules."""

from pathlib import Path

ENV_LLM_BASE_URL = "LLM_BASE_URL"
ENV_LLM_API_KEY = "LLM_API_KEY"
ENV_LLM_MODEL = "LLM_MODEL"

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR_NAME = "corpus"
INDEX_DIR_NAME = "index"
TRACES_DIR_NAME = "traces"
VIEWER_DIR_NAME = "viewer"

API_KEY_MASK = "***"

STOPWORDS_FR = frozenset(
    """
    a au aux avec ce ces cet cette dans de des du elle elles en est et il
    ils je la le les leur leurs lui ma mais me mes moi mon ne nos notre
    nous ou par pas pour qu que qui sa se ses son sur ta te tes toi ton tu
    un une vos votre vous y ete etre sont sera ont avait avoir fait comme
    plus si sans sous tout tous toute toutes aussi donc car ni quel quelle
    quels quelles combien quoi dont ainsi cela celui celle
    """.split()
)

STOPWORDS_EN = frozenset(
    """
    a an and are as at be been but by can did do does for from had has have
    he her his how i if in into is it its me my no not of on or our she so
    than that the their them then there these they this those to too us
    was we were what when where which who whom why will with would you
    your
    """.split()
)

STOPWORDS = STOPWORDS_FR | STOPWORDS_EN

# Corpus and pipeline share this glob.
PDF_GLOB = "*.pdf"

# Untrusted text delimited inside LLM prompts.
QUESTION_TAG = "question"
DOCUMENT_TAG = "document"
UNTRUSTED_TAG_PATTERN = r"<(/?){tag}"
# The doubled backslash survives the re.sub template: "<\question".
UNTRUSTED_TAG_ESCAPE = r"<\\{tag}"
UNTRUSTED_BLOCK = "<{tag}{attributes}>\n{text}\n</{tag}>"
