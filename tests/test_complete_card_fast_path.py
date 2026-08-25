from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from cardlayout.models.card_side import CardSide
from cardlayout.models.card_size import MALAYSIA_IC
from cardlayout.services.card_detector import CardDetector
from cardlayout.services.card_processing import CardProcessingService


def _bounds(points: np.ndarray) -> tuple[int, int, int, int]:
    return (
        int(points[:, 0].min()),
        int(points[:, 1].min()),
        int(points[:, 0].max()),
        int(points[:, 1].max()),
    )


def _iou(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    union = (
        (first[2] - first[0]) * (first[3] - first[1])
        + (second[2] - second[0]) * (second[3] - second[1])
        - intersection
    )
    return intersection / max(1.0, float(union))


def _complete_card_scene(
    feature: str,
    *,
    angle: float = 0.0,
    light_background: bool = False,
) -> tuple[Image.Image, np.ndarray]:
    background = (230, 232, 235) if light_background else (46, 52, 59)
    pixels = np.full((760, 1100, 3), background, dtype=np.uint8)
    card = cv2.boxPoints(((550, 380), (720, 454), angle)).astype(np.int32)
    fill = (55, 92, 128) if feature == "back" else (205, 218, 226)
    edge = (20, 24, 28) if not light_background else (55, 62, 68)

    # Use card-relative coordinates so the same graphics rotate with the card.
    local = np.full((454, 720, 3), fill, dtype=np.uint8)
    local_mask = np.full((454, 720), 255, dtype=np.uint8)
    if feature == "rounded":
        local_mask.fill(0)
        radius = 34
        cv2.rectangle(local_mask, (radius, 0), (719 - radius, 453), 255, -1)
        cv2.rectangle(local_mask, (0, radius), (719, 453 - radius), 255, -1)
        for center in (
            (radius, radius),
            (719 - radius, radius),
            (719 - radius, 453 - radius),
            (radius, 453 - radius),
        ):
            cv2.circle(local_mask, center, radius, 255, -1, cv2.LINE_AA)
        inner = cv2.erode(local_mask, np.ones((7, 7), np.uint8))
        local[(local_mask > 0) & (inner == 0)] = edge
    if feature in {"front", "portrait", "dense", "rounded"}:
        cv2.rectangle(local, (470, 92), (675, 355), (28, 36, 44), 8)
        cv2.circle(local, (572, 190), 62, (110, 126, 138), -1, cv2.LINE_AA)
    if feature in {"front", "chip"}:
        cv2.rectangle(local, (72, 145), (230, 270), (20, 25, 30), 9)
        for x in (110, 155, 200):
            cv2.line(local, (x, 150), (x, 265), (185, 150, 50), 4)
    line_count = 11 if feature == "dense" else 6
    for row in range(line_count):
        y = 55 + row * 29
        cv2.line(local, (58, y), (390, y), (38, 46, 54), 5, cv2.LINE_AA)
    if feature == "back":
        cv2.circle(local, (90, 75), 18, (72, 110, 145), -1, cv2.LINE_AA)

    source = np.asarray(((0, 0), (719, 0), (719, 453), (0, 453)), np.float32)
    destination = card.astype(np.float32)
    transform = cv2.getPerspectiveTransform(source, destination)
    warped = cv2.warpPerspective(local, transform, (1100, 760))
    mask = cv2.warpPerspective(local_mask, transform, (1100, 760))
    pixels[mask > 0] = warped[mask > 0]
    if feature != "rounded":
        cv2.polylines(pixels, [card], True, edge, 6, cv2.LINE_AA)
    return Image.fromarray(pixels), card


def test_complete_card_fast_path_rejects_bottom_right_internal_region() -> None:
    image, card = _complete_card_scene("front")
    result = CardDetector(MALAYSIA_IC, debug=True).detect(image)

    assert result.success
    assert result.bounding_box is not None
    assert _iou(result.bounding_box, _bounds(card)) > 0.94
    fast_path = result.debug_info["complete_card_fast_path"]
    assert fast_path["used"] is True
    assert fast_path["proposal_found"] is True
    assert fast_path["full_card_boundary_score"] >= 0.78
    assert fast_path["full_card_coverage_score"] >= 0.78
    assert fast_path["proposal_normal_iou"] >= 0.90

    side = CardSide(
        side="front",
        source_path=Path("complete-front.png"),
        source_type="image",
        source_page=None,
        original_image=image.copy(),
        processed_image=image.copy(),
    )
    CardProcessingService(CardDetector(MALAYSIA_IC)).detect(side)
    assert side.automatic_perspective_result is not None
    assert side.automatic_perspective_result.success
    assert side.rectified_image is not None
    assert side.rectified_image.width > side.rectified_image.height


@pytest.mark.parametrize(
    ("feature", "angle", "light_background"),
    [
        ("front", 0.0, False),
        ("back", 0.0, True),
        ("portrait", 0.0, False),
        ("chip", 0.0, True),
        ("dense", 0.0, False),
        ("rounded", 0.0, True),
        ("front", 9.0, False),
    ],
    ids=(
        "complete-front",
        "complete-back",
        "portrait-rectangle",
        "chip-rectangle",
        "dense-text",
        "rounded-corners",
        "slightly-rotated",
    ),
)
def test_complete_card_variants_keep_the_outer_perimeter(
    feature: str, angle: float, light_background: bool
) -> None:
    image, card = _complete_card_scene(
        feature,
        angle=angle,
        light_background=light_background,
    )
    result = CardDetector(MALAYSIA_IC, debug=True).detect(image)

    assert result.success
    assert result.bounding_box is not None
    assert _iou(result.bounding_box, _bounds(card)) > 0.92
    assert result.debug_info["complete_card_fast_path"]["used"] is True
    assert result.debug_info["selected_candidate"]["internal_subregion_penalty"] == 0


def _near_frame_regression_scene(
    internal_position: str,
) -> Image.Image:
    rng = np.random.default_rng(17)
    pixels = np.full((328, 496, 3), (157, 151, 143), dtype=np.int16)
    pixels += rng.integers(-7, 8, size=pixels.shape, dtype=np.int16)
    pixels = np.clip(pixels, 0, 255).astype(np.uint8)
    card_mask = np.zeros((328, 496), dtype=np.uint8)
    radius = 20
    cv2.rectangle(card_mask, (radius, 4), (475, 323), 255, -1)
    cv2.rectangle(card_mask, (3, radius), (492, 307), 255, -1)
    for center in ((23, 24), (472, 24), (472, 303), (23, 303)):
        cv2.circle(card_mask, center, radius, 255, -1, cv2.LINE_AA)
    pixels[card_mask > 0] = (145, 188, 211)
    inner = cv2.erode(card_mask, np.ones((5, 5), np.uint8))
    pixels[(card_mask > 0) & (inner == 0)] = (120, 150, 165)

    if internal_position == "center_left":
        first, second = (65, 112), (285, 251)
    else:
        first, second = (270, 142), (477, 273)
    cv2.rectangle(pixels, first, second, (34, 40, 46), 6, cv2.LINE_AA)
    for y in range(first[1] + 20, second[1] - 8, 20):
        cv2.line(
            pixels,
            (first[0] + 14, y),
            (second[0] - 14, y),
            (72, 82, 90),
            4,
            cv2.LINE_AA,
        )
    return Image.fromarray(pixels)


@pytest.mark.parametrize("internal_position", ["center_left", "lower_right"])
def test_near_frame_low_texture_card_rejects_large_internal_regions(
    internal_position: str,
) -> None:
    image = _near_frame_regression_scene(internal_position)
    result = CardDetector(MALAYSIA_IC, debug=True).detect(image)

    assert result.success
    assert result.method == "already_cropped"
    assert result.bounding_box == (0, 0, image.width, image.height)
    assert result.polygon_points == (
        (0.0, 0.0),
        (float(image.width - 1), 0.0),
        (float(image.width - 1), float(image.height - 1)),
        (0.0, float(image.height - 1)),
    )


def test_card_ratio_canvas_does_not_hide_a_smaller_card_inside_it() -> None:
    pixels = np.full((540, 856, 3), (48, 54, 61), dtype=np.uint8)
    card = cv2.boxPoints(((428, 270), (500, 315), -4.0)).astype(np.int32)
    cv2.fillConvexPoly(pixels, card, (202, 216, 226))
    cv2.polylines(pixels, [card], True, (18, 22, 26), 6, cv2.LINE_AA)
    cv2.rectangle(pixels, (410, 225), (610, 350), (28, 35, 42), 6)

    result = CardDetector(MALAYSIA_IC, debug=True).detect(Image.fromarray(pixels))

    assert result.success
    assert result.method != "already_cropped"
    assert result.bounding_box is not None
    assert _iou(result.bounding_box, _bounds(card)) > 0.90


def test_smaller_fast_proposal_cannot_override_normal_outer_candidate() -> None:
    image, _ = _complete_card_scene("front")
    original = np.asarray(image)
    detector = CardDetector(MALAYSIA_IC, debug=True)
    fast = detector._run_pass(  # noqa: SLF001 - targeted detector regression
        original,
        target_long_edge=detector.config.fast_long_edge,
        name="fast_contour",
        extended_color=False,
        include_lines=False,
        include_partial=False,
    )
    detailed = detector._run_pass(  # noqa: SLF001
        original,
        target_long_edge=detector.config.detailed_long_edge,
        name="detailed_hybrid",
        extended_color=True,
        include_lines=True,
        include_partial=False,
    )
    candidates = detector._contextual_rank(  # noqa: SLF001
        detector._fuse_candidates(fast.candidates + detailed.candidates),  # noqa: SLF001
        original,
    )
    normal = candidates[0]
    partial = next(
        candidate
        for candidate in candidates[1:]
        if candidate.area_ratio <= normal.area_ratio * 0.70
        and candidate.candidate_id in normal.contains_candidates
    )

    diagnostics = detector._validate_complete_card_proposal(  # noqa: SLF001
        partial,
        [normal],
        {"used": False, "proposal_found": True},
    )

    assert diagnostics["used"] is False
    assert diagnostics["proposal_normal_area_ratio"] > 1.14
    assert diagnostics["reason"] == (
        "Proposal rejected because normal geometry did not agree"
    )
