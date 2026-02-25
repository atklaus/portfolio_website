"""Inference helpers for the Landscape Image Prediction page.

The model expects 150x150 RGB tensors. We intentionally use full-image coverage:
1) decode once
2) aspect-preserving resize (for stability + speed bounds)
3) deterministic overlapping tiles that include image edges
4) mean aggregation across tile probabilities
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np

MODEL_INPUT_SIZE = (150, 150)
DEFAULT_TILE_OVERLAP = 30
DEFAULT_LEGACY_TILE_OVERLAP = 10
DEFAULT_MAX_LONG_EDGE = 1200
DEFAULT_MIN_SHORT_EDGE = 150
CLASS_NAMES = ("buildings", "forest", "glacier", "mountain", "sea", "street")


@dataclass(frozen=True)
class PreprocessMetadata:
    original_height: int
    original_width: int
    resized_height: int
    resized_width: int
    resize_scale: float
    tile_count: int
    tile_size: tuple[int, int]
    overlap: int
    strategy: str


def decode_uploaded_image(image_bytes: bytes) -> np.ndarray:
    """Decode bytes into an RGB image."""
    buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    bgr_image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if bgr_image is None:
        raise ValueError("Could not decode image bytes.")
    return cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)


def _resize_for_inference(
    image_rgb: np.ndarray,
    *,
    max_long_edge: int = DEFAULT_MAX_LONG_EDGE,
    min_short_edge: int = DEFAULT_MIN_SHORT_EDGE,
) -> tuple[np.ndarray, float]:
    """Resize with aspect ratio preserved to bound work while keeping full frame."""
    height, width = image_rgb.shape[:2]
    short_edge = min(height, width)
    long_edge = max(height, width)
    scale = 1.0

    if short_edge < min_short_edge:
        scale = min_short_edge / float(short_edge)
    elif long_edge > max_long_edge:
        scale = max_long_edge / float(long_edge)

    if abs(scale - 1.0) < 1e-6:
        return image_rgb, 1.0

    new_width = max(1, int(round(width * scale)))
    new_height = max(1, int(round(height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    resized = cv2.resize(image_rgb, (new_width, new_height), interpolation=interpolation)
    return resized, scale


def _grid_positions(length: int, tile_size: int, stride: int) -> list[int]:
    """Return deterministic tile starts that always include the final edge tile."""
    if length <= tile_size:
        return [0]
    last_start = length - tile_size
    starts = list(range(0, last_start + 1, stride))
    if starts[-1] != last_start:
        starts.append(last_start)
    return starts


def tile_image_full_coverage(
    image_rgb: np.ndarray,
    *,
    tile_size: tuple[int, int] = MODEL_INPUT_SIZE,
    overlap: int = DEFAULT_TILE_OVERLAP,
) -> np.ndarray:
    """Create deterministic overlapping tiles with complete image coverage."""
    tile_h, tile_w = tile_size
    stride_h = max(1, tile_h - overlap)
    stride_w = max(1, tile_w - overlap)
    height, width = image_rgb.shape[:2]

    y_starts = _grid_positions(height, tile_h, stride_h)
    x_starts = _grid_positions(width, tile_w, stride_w)

    tiles = np.empty((len(y_starts) * len(x_starts), tile_h, tile_w, 3), dtype=np.uint8)
    idx = 0
    for y in y_starts:
        for x in x_starts:
            tiles[idx] = image_rgb[y : y + tile_h, x : x + tile_w]
            idx += 1
    return tiles


def tile_image_legacy_sparse(
    image_rgb: np.ndarray,
    *,
    tile_size: tuple[int, int] = MODEL_INPUT_SIZE,
    overlap: int = DEFAULT_LEGACY_TILE_OVERLAP,
) -> np.ndarray:
    """Replicate the original page's sparse tiling behavior for compatibility."""
    tile_h, tile_w = tile_size
    stride = max(1, tile_h - overlap)
    height, width = image_rgb.shape[:2]
    tiles: list[np.ndarray] = []

    # Keep x-major iteration and partial-tile drop behavior from legacy page code.
    x_stop = max(0, width - tile_w + stride)
    y_stop = max(0, height - tile_h + stride)
    for x in range(0, x_stop, stride):
        for y in range(0, y_stop, stride):
            tile = image_rgb[y : y + tile_h, x : x + tile_w]
            if tile.shape[0] == tile_h and tile.shape[1] == tile_w:
                tiles.append(tile)

    if not tiles:
        return np.empty((0, tile_h, tile_w, 3), dtype=np.uint8)
    return np.stack(tiles, axis=0)


def prepare_model_batch(
    image_rgb: np.ndarray,
    *,
    tile_size: tuple[int, int] = MODEL_INPUT_SIZE,
    overlap: int = DEFAULT_TILE_OVERLAP,
    max_long_edge: int = DEFAULT_MAX_LONG_EDGE,
    min_short_edge: int = DEFAULT_MIN_SHORT_EDGE,
    strategy: str = "full_coverage",
) -> tuple[np.ndarray, PreprocessMetadata]:
    """Build float32 model input batch plus metadata for instrumentation."""
    original_height, original_width = image_rgb.shape[:2]
    if strategy == "legacy_sparse":
        resized_image = image_rgb
        resize_scale = 1.0
        resized_height, resized_width = resized_image.shape[:2]
        tiles = tile_image_legacy_sparse(
            resized_image,
            tile_size=tile_size,
            overlap=overlap,
        )
    else:
        resized_image, resize_scale = _resize_for_inference(
            image_rgb,
            max_long_edge=max_long_edge,
            min_short_edge=min_short_edge,
        )
        resized_height, resized_width = resized_image.shape[:2]
        tiles = tile_image_full_coverage(
            resized_image,
            tile_size=tile_size,
            overlap=overlap,
        )

    if tiles.shape[0] == 0:
        raise ValueError(
            "No tiles were generated from this image. Try a larger image or choose full coverage mode."
        )

    # Keep the same numeric range used by the shipped model artifact.
    batch = tiles.astype(np.float32, copy=False)
    metadata = PreprocessMetadata(
        original_height=original_height,
        original_width=original_width,
        resized_height=resized_height,
        resized_width=resized_width,
        resize_scale=float(resize_scale),
        tile_count=int(tiles.shape[0]),
        tile_size=tile_size,
        overlap=overlap,
        strategy=strategy,
    )
    return batch, metadata


def aggregate_predictions(
    tile_probabilities: np.ndarray,
    *,
    class_names: Sequence[str] = CLASS_NAMES,
    top_k: int = 5,
) -> tuple[int, float, np.ndarray, list[dict[str, float | str]]]:
    """Average tile probabilities and return top-k labels."""
    if tile_probabilities.ndim != 2:
        raise ValueError("Expected tile probabilities with shape [n_tiles, n_classes].")

    mean_probabilities = tile_probabilities.mean(axis=0)
    top_k = max(1, min(top_k, mean_probabilities.shape[0]))
    top_indices = np.argsort(mean_probabilities)[::-1][:top_k]
    rows = []
    for idx in top_indices:
        label = class_names[idx] if idx < len(class_names) else f"class_{idx}"
        rows.append({"label": str(label), "probability": float(mean_probabilities[idx])})

    top_index = int(np.argmax(mean_probabilities))
    top_probability = float(mean_probabilities[top_index])
    return top_index, top_probability, mean_probabilities, rows
