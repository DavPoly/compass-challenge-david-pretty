"""Render the PDF page holding an evidence quote with it highlighted."""

from dataclasses import dataclass
from pathlib import Path

import pdfplumber
from pdfplumber.page import Page
from pdfplumber.pdf import PDF
from PIL import Image, ImageDraw

from archive.validation.answer_model import Evidence
from archive.viewer.quote_locate_utils import (
    Box,
    QuoteMatch,
    Word,
    locate_quote,
)

RENDER_DPI = 110
POINTS_PER_INCH = 72
CROP_MARGIN_PT = 36.0
FALLBACK_PAGE_NUMBER = 1
FULL_SUFFIX = "_page.png"
CROP_SUFFIX = "_crop.png"
OVERLAY_ALPHA = 70
OUTLINE_WIDTH_PX = 2
VALUE_OUTLINE_WIDTH_PX = 3
VERIFIED_RGB = (30, 160, 70)
UNVERIFIED_RGB = (210, 50, 50)
VALUE_VERIFIED_RGB = (0, 90, 30)
VALUE_UNVERIFIED_RGB = (130, 0, 0)


@dataclass(frozen=True)
class RenderedEvidence:
    """Result of rendering one evidence quote.

    Attributes:
        page: 1-based page shown, or None when nothing was rendered.
        crop_path: Crop around the quote, None when not located.
        full_path: Full page image.
        is_located: Whether the quote was found on a page.
    """

    page: int | None
    crop_path: Path | None
    full_path: Path | None
    is_located: bool


def _page_words(page: Page) -> list[Word]:
    return [
        Word(
            raw["text"],
            float(raw["x0"]),
            float(raw["top"]),
            float(raw["x1"]),
            float(raw["bottom"]),
        )
        for raw in page.extract_words()
    ]


def _scaled(box: Box, scale: float) -> tuple[float, float, float, float]:
    return (
        box.x0 * scale,
        box.top * scale,
        box.x1 * scale,
        box.bottom * scale,
    )


def _draw_boxes(
    image: Image.Image, match: QuoteMatch, is_verified: bool
) -> Image.Image:
    scale = RENDER_DPI / POINTS_PER_INCH
    quote_rgb = VERIFIED_RGB if is_verified else UNVERIFIED_RGB
    value_rgb = VALUE_VERIFIED_RGB if is_verified else VALUE_UNVERIFIED_RGB
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for box in match.boxes:
        draw.rectangle(
            _scaled(box, scale),
            fill=(*quote_rgb, OVERLAY_ALPHA),
            outline=quote_rgb,
            width=OUTLINE_WIDTH_PX,
        )
    for box in match.value_boxes:
        draw.rectangle(
            _scaled(box, scale),
            outline=value_rgb,
            width=VALUE_OUTLINE_WIDTH_PX,
        )
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _crop(
    image: Image.Image, match: QuoteMatch, page_width_pt: float
) -> Image.Image:
    scale = RENDER_DPI / POINTS_PER_INCH
    top = min(box.top for box in match.boxes) - CROP_MARGIN_PT
    bottom = max(box.bottom for box in match.boxes) + CROP_MARGIN_PT
    left = max(0.0, min(box.x0 for box in match.boxes) - CROP_MARGIN_PT)
    right = min(
        page_width_pt, max(box.x1 for box in match.boxes) + CROP_MARGIN_PT
    )
    return image.crop(
        (
            round(left * scale),
            max(0, round(top * scale)),
            round(right * scale),
            min(image.height, round(bottom * scale)),
        )
    )


def _find_match(pdf: PDF, evidence: Evidence) -> tuple[int, QuoteMatch] | None:
    for page_number, page in enumerate(pdf.pages, start=1):
        match = locate_quote(_page_words(page), evidence.quote, evidence.value)
        if match is not None:
            return page_number, match
    return None


def _page_image(page: Page) -> Image.Image:
    return page.to_image(resolution=RENDER_DPI).original.convert("RGB")


def _save(image: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def render_evidence(
    pdf_path: Path,
    evidence: Evidence,
    is_verified: bool,
    out_stem: Path,
) -> RenderedEvidence:
    """Render the page of a quote with the quote highlighted.

    The first page where the quote is found is drawn with its quote
    lines filled (green when verified, red otherwise) and the value
    outlined darker. Saves ``<out_stem>_page.png`` (full page) and
    ``<out_stem>_crop.png`` (band around the quote). When the quote is
    found nowhere, page 1 is saved unmarked and no crop is written.

    Args:
        pdf_path: The source PDF.
        evidence: Quote, value and document id to highlight.
        is_verified: Whether the quote passed grounding (colors only).
        out_stem: Output path prefix; its parent is created.

    Returns:
        Page number, image paths and whether the quote was located.

    Raises:
        Exception: Whatever pdfplumber raises for a missing, unreadable
            or empty PDF; the caller handles it.
    """
    full_path = out_stem.parent / (out_stem.name + FULL_SUFFIX)
    with pdfplumber.open(pdf_path) as pdf:
        found = _find_match(pdf, evidence)
        if found is None:
            image = _page_image(pdf.pages[FALLBACK_PAGE_NUMBER - 1])
            _save(image, full_path)
            return RenderedEvidence(
                FALLBACK_PAGE_NUMBER, None, full_path, False
            )
        page_number, match = found
        page = pdf.pages[page_number - 1]
        image = _draw_boxes(_page_image(page), match, is_verified)
        crop = _crop(image, match, float(page.width))
    crop_path = out_stem.parent / (out_stem.name + CROP_SUFFIX)
    _save(image, full_path)
    _save(crop, crop_path)
    return RenderedEvidence(page_number, crop_path, full_path, True)
