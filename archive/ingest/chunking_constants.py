"""Constants of the chunking service."""

CHUNK_SINGLE_MAX_TOKENS = 800
CHUNK_TARGET_TOKENS = 400
CHUNK_OVERLAP_TOKENS = 50
CHUNK_PARAGRAPH_SNAP_TOKENS = 60
CHUNK_ID_SEPARATOR = "#"
PARAGRAPH_BREAK = "\n\n"
# Tokens are approximated by whitespace-separated words.
WORD_PATTERN = r"\S+"
