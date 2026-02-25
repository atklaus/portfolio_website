"""Landscape Image Prediction page.

UI and inference refresh highlights:
- product-style two-column layout
- cached model loading
- deterministic full-image tiling (edge-aligned)
- lightweight decode/preprocess/inference/postprocess timing
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
import streamlit as st

from app.layout.header import page_header
from lib.ops.memory import log_mem
from projects.landscape_img.inference import (
    CLASS_NAMES,
    DEFAULT_LEGACY_TILE_OVERLAP,
    DEFAULT_MAX_LONG_EDGE,
    DEFAULT_TILE_OVERLAP,
    MODEL_INPUT_SIZE,
    aggregate_predictions,
    decode_uploaded_image,
    prepare_model_batch,
)
from shared.settings import get_settings
from shared.telemetry import page_guard

ROOT_DIR = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT_DIR / "projects" / "landscape_img" / "model"
DATASET_SIZE_APPROX = 5000


@st.cache_resource(show_spinner=False)
def get_tf():
    """Lazy-load TensorFlow only when inference needs it."""
    import tensorflow as tf

    return tf


@st.cache_resource(show_spinner="Loading model...")
def load_model():
    """Load and cache the TensorFlow model once per process."""
    log_mem("landscape_model_load:before")
    tf = get_tf()
    model = tf.keras.models.load_model(str(MODEL_DIR), compile=False)
    model.trainable = False
    log_mem("landscape_model_load:after")
    return model


@st.cache_data(show_spinner=False)
def load_class_names() -> tuple[str, ...]:
    """Cache class names alongside model state for stable rendering."""
    return tuple(CLASS_NAMES)


def _hero_runtime_badge() -> str:
    """Render a fast, no-import runtime badge for initial page load."""
    backend = st.session_state.get("landscape_inference_backend", "CPU (stable)")
    if backend == "GPU (experimental)":
        return "Local model | GPU inference"
    if backend == "Auto":
        return "Local model | Auto backend"
    return "Local model | CPU inference"


def _card_container():
    try:
        return st.container(border=True)
    except TypeError:
        return st.container()


def _inject_page_css() -> None:
    st.markdown(
        """
<style>
.landscape-shell {
  max-width: 1240px;
  margin: 0 auto;
  padding: 0.2rem 0 0.9rem 0;
}
.landscape-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
  flex-wrap: wrap;
  margin-bottom: 0.35rem;
}
.landscape-title {
  margin: 0;
  font-size: 1.8rem;
  color: var(--ads-ink);
  line-height: 1.2;
}
.landscape-subtitle {
  margin: 0.3rem 0 0 0;
  color: var(--ads-muted);
  font-size: 0.95rem;
}
.landscape-pill {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  border: 1px solid rgba(155, 231, 216, 0.25);
  padding: 0.25rem 0.75rem;
  color: var(--ads-accent);
  background: rgba(155, 231, 216, 0.08);
  font-size: 0.78rem;
  font-weight: 600;
  white-space: nowrap;
}
.landscape-section-title {
  margin-top: 0;
  margin-bottom: 0.4rem;
}
div[data-testid="stFileUploader"] {
  margin-bottom: 0.65rem;
}
@media (max-width: 768px) {
  .landscape-title {
    font-size: 1.45rem;
  }
  .landscape-subtitle {
    font-size: 0.9rem;
  }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _render_hero() -> None:
    st.markdown(
        f"""
<div class="landscape-shell">
  <div class="landscape-hero">
    <div>
      <h1 class="landscape-title">Landscape Image Prediction</h1>
      <p class="landscape-subtitle">Trained on ~{DATASET_SIZE_APPROX:,} labeled images, predicts the scene category for uploaded photos.</p>
    </div>
    <div class="landscape-pill">{_hero_runtime_badge()}</div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def _run_inference(
    uploaded_bytes: bytes,
    class_names: tuple[str, ...],
    *,
    preprocess_mode_override: str | None = None,
    inference_backend_override: str | None = None,
) -> dict:
    timings_ms: dict[str, float] = {}

    decode_start = perf_counter()
    image_rgb = decode_uploaded_image(uploaded_bytes)
    model_image = image_rgb
    timings_ms["decode"] = (perf_counter() - decode_start) * 1000

    preprocess_start = perf_counter()
    preprocess_mode = preprocess_mode_override or st.session_state.get(
        "landscape_preprocess_mode",
        "Legacy sparse tiling (original)",
    )
    strategy = "legacy_sparse" if preprocess_mode == "Legacy sparse tiling (original)" else "full_coverage"
    overlap = DEFAULT_LEGACY_TILE_OVERLAP if strategy == "legacy_sparse" else DEFAULT_TILE_OVERLAP
    max_long_edge = 10000 if strategy == "legacy_sparse" else DEFAULT_MAX_LONG_EDGE
    batch, preprocess_meta = prepare_model_batch(
        model_image,
        tile_size=MODEL_INPUT_SIZE,
        overlap=overlap,
        max_long_edge=max_long_edge,
        strategy=strategy,
    )
    timings_ms["preprocess"] = (perf_counter() - preprocess_start) * 1000

    model_start = perf_counter()
    model = load_model()
    timings_ms["model_init"] = (perf_counter() - model_start) * 1000

    inference_start = perf_counter()
    inference_backend = inference_backend_override or st.session_state.get(
        "landscape_inference_backend",
        "CPU (stable)",
    )
    applied_backend = inference_backend
    batch_size = min(64, len(batch))
    if inference_backend == "CPU (stable)":
        tf = get_tf()
        with tf.device("/CPU:0"):
            tile_probabilities = model.predict(batch, verbose=0, batch_size=batch_size)
    elif inference_backend == "GPU (experimental)":
        tf = get_tf()
        try:
            with tf.device("/GPU:0"):
                tile_probabilities = model.predict(batch, verbose=0, batch_size=batch_size)
        except Exception:
            with tf.device("/CPU:0"):
                tile_probabilities = model.predict(batch, verbose=0, batch_size=batch_size)
            applied_backend = "CPU (fallback)"
    else:
        tile_probabilities = model.predict(batch, verbose=0, batch_size=batch_size)
    timings_ms["inference"] = (perf_counter() - inference_start) * 1000
    tile_top_indices = tile_probabilities.argmax(axis=1)
    tile_vote_rows = []
    for idx, label in enumerate(class_names):
        count = int((tile_top_indices == idx).sum())
        tile_vote_rows.append({"Scene": label, "Tile votes": count})

    postprocess_start = perf_counter()
    top_idx, top_prob, mean_probs, top_rows = aggregate_predictions(
        tile_probabilities, class_names=class_names, top_k=5
    )
    timings_ms["postprocess"] = (perf_counter() - postprocess_start) * 1000
    safe_probs = np.clip(mean_probs, 1e-12, 1.0)
    mean_entropy = float(-(safe_probs * np.log(safe_probs)).sum())
    mean_tile_max = float(tile_probabilities.max(axis=1).mean())

    return {
        "image_rgb": image_rgb,
        "preprocess_meta": preprocess_meta,
        "top_index": top_idx,
        "top_probability": top_prob,
        "top_label": class_names[top_idx],
        "mean_probabilities": mean_probs,
        "top_rows": top_rows,
        "timings_ms": timings_ms,
        "tile_vote_rows": tile_vote_rows,
        "batch_shape": list(batch.shape),
        "applied_backend": applied_backend,
        "mean_entropy": mean_entropy,
        "mean_tile_max": mean_tile_max,
    }


def _run_compatibility_sweep(uploaded_bytes: bytes, class_names: tuple[str, ...]) -> pd.DataFrame:
    """Run fixed CPU checks across preprocessing combinations."""
    configs = [
        ("Legacy sparse tiling (original)",),
        ("Full coverage tiling (edge-aligned)",),
    ]
    rows = []
    for (preprocess_mode,) in configs:
        result = _run_inference(
            uploaded_bytes,
            class_names,
            preprocess_mode_override=preprocess_mode,
            inference_backend_override="CPU (stable)",
        )
        rows.append(
            {
                "Preprocess": preprocess_mode,
                "Color": "RGB",
                "Top label": result["top_label"],
                "Confidence": result["top_probability"],
                "Entropy": result["mean_entropy"],
                "Tile max avg": result["mean_tile_max"],
                "Tiles": result["preprocess_meta"].tile_count,
            }
        )
    return pd.DataFrame(rows)


def _format_top_k_table(top_rows: list[dict[str, float | str]]) -> pd.DataFrame:
    top_df = pd.DataFrame(top_rows).rename(columns={"label": "Scene", "probability": "Probability"})
    top_df["Probability %"] = (top_df["Probability"] * 100.0).map(lambda val: f"{val:.2f}%")
    return top_df


with page_guard(os.path.basename(__file__)):
    settings = get_settings()
    if settings.safe_mode:
        st.warning("Safe mode is enabled. This page is disabled to reduce memory usage.")
        st.stop()

    page_header("Landscape Image Prediction", page_name=os.path.basename(__file__))
    _inject_page_css()
    _render_hero()
    class_names = load_class_names()

    if "landscape_file_digest" not in st.session_state:
        st.session_state["landscape_file_digest"] = None
    if "landscape_result" not in st.session_state:
        st.session_state["landscape_result"] = None
    if "landscape_last_preprocess_mode" not in st.session_state:
        st.session_state["landscape_last_preprocess_mode"] = None
    if "landscape_last_backend" not in st.session_state:
        st.session_state["landscape_last_backend"] = None
    if "landscape_compat_result" not in st.session_state:
        st.session_state["landscape_compat_result"] = None
    if "landscape_inference_backend" not in st.session_state:
        st.session_state["landscape_inference_backend"] = "CPU (stable)"

    left_col, right_col = st.columns([1.05, 0.95], gap="large")

    with left_col:
        with _card_container():
            st.markdown("#### Upload + Preview")
            st.selectbox(
                "Preprocessing strategy",
                options=[
                    "Legacy sparse tiling (original)",
                    "Full coverage tiling (edge-aligned)",
                ],
                index=0,
                key="landscape_preprocess_mode",
                help=(
                    "Legacy mode reproduces the original page behavior for model compatibility checks. "
                    "Full coverage mode includes edge tiles and applies bounded resize for faster deterministic coverage."
                ),
            )
            st.caption("Input color pipeline: **RGB**")
            st.selectbox(
                "Execution backend",
                options=["CPU (stable)", "Auto", "GPU (experimental)"],
                index=0,
                key="landscape_inference_backend",
                help=(
                    "CPU is slower but more stable for this legacy TensorFlow artifact. "
                    "Use GPU only for testing throughput."
                ),
            )
            uploaded_file = st.file_uploader(
                "Choose an image",
                type=["jpg", "jpeg", "png", "webp", "bmp"],
                key="submit_landscape",
                help="Supports common image formats. Inference runs locally in this app process.",
            )
            rerun_clicked = st.button(
                "Run inference",
                type="primary",
                use_container_width=True,
                disabled=uploaded_file is None,
                key="landscape_run_inference",
            )
            compat_clicked = st.button(
                "Run compatibility check (CPU, 2 modes)",
                use_container_width=True,
                disabled=uploaded_file is None,
                key="landscape_run_compat",
                help="Compares legacy and full-coverage tiling under CPU stable execution.",
            )

    result = None
    if uploaded_file is not None:
        uploaded_bytes = uploaded_file.getvalue()
        current_digest = hashlib.sha256(uploaded_bytes).hexdigest()
        current_preprocess_mode = st.session_state.get(
            "landscape_preprocess_mode",
            "Legacy sparse tiling (original)",
        )
        current_backend = st.session_state.get("landscape_inference_backend", "CPU (stable)")
        digest_changed = current_digest != st.session_state["landscape_file_digest"]
        preprocess_mode_changed = (
            current_preprocess_mode != st.session_state["landscape_last_preprocess_mode"]
        )
        backend_changed = current_backend != st.session_state["landscape_last_backend"]
        if digest_changed:
            st.session_state["landscape_file_digest"] = current_digest
            st.session_state["landscape_result"] = None
            st.session_state["landscape_compat_result"] = None
        if preprocess_mode_changed:
            st.session_state["landscape_result"] = None
            st.session_state["landscape_last_preprocess_mode"] = current_preprocess_mode
        if backend_changed:
            st.session_state["landscape_result"] = None
            st.session_state["landscape_last_backend"] = current_backend

        should_run = (
            digest_changed
            or preprocess_mode_changed
            or backend_changed
            or rerun_clicked
            or st.session_state["landscape_result"] is None
        )
        if should_run:
            with st.spinner("Running landscape inference..."):
                log_mem("landscape_predict:before_model")
                try:
                    st.session_state["landscape_result"] = _run_inference(uploaded_bytes, class_names)
                except ValueError as exc:
                    st.error(str(exc))
                    st.session_state["landscape_result"] = None
                log_mem("landscape_predict:after_model")

        if compat_clicked:
            with st.spinner("Running compatibility check..."):
                try:
                    st.session_state["landscape_compat_result"] = _run_compatibility_sweep(
                        uploaded_bytes,
                        class_names,
                    )
                except ValueError as exc:
                    st.error(str(exc))
                    st.session_state["landscape_compat_result"] = None

        result = st.session_state["landscape_result"]
    else:
        st.session_state["landscape_file_digest"] = None
        st.session_state["landscape_result"] = None
        st.session_state["landscape_last_preprocess_mode"] = None
        st.session_state["landscape_last_backend"] = None
        st.session_state["landscape_compat_result"] = None

    with left_col:
        with _card_container():
            if result is None:
                st.info("Upload an image to run prediction.")
            else:
                meta = result["preprocess_meta"]
                st.image(
                    result["image_rgb"],
                    caption=f"Original preview ({meta.original_width} x {meta.original_height})",
                    use_container_width=True,
                )
                m1, m2 = st.columns(2)
                m1.metric("Tiles", f"{meta.tile_count}")
                m2.metric("Resize scale", f"{meta.resize_scale:.2f}x")

    with right_col:
        with _card_container():
            st.markdown("#### Results")
            if result is None:
                st.caption("Prediction details appear here after upload.")
            else:
                st.markdown(f"### Top Prediction: `{result['top_label'].upper()}`")
                st.metric("Confidence", f"{result['top_probability']:.2%}")

                top_df = _format_top_k_table(result["top_rows"])
                st.dataframe(
                    top_df,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Probability": st.column_config.ProgressColumn(
                            "Probability",
                            min_value=0.0,
                            max_value=1.0,
                            format="%.3f",
                        ),
                    },
                )
                st.bar_chart(
                    top_df.set_index("Scene")["Probability"],
                    height=220,
                    use_container_width=True,
                )

                meta = result["preprocess_meta"]
                timings = result["timings_ms"]
                if meta.strategy == "legacy_sparse":
                    strategy_desc = (
                        "decode once -> RGB conversion -> original sparse tiling -> mean tile probability aggregation"
                    )
                    coverage_note = "Legacy mode matches original behavior and may skip some edge regions."
                else:
                    strategy_desc = (
                        "decode once -> RGB conversion -> aspect-preserving resize -> deterministic edge-aligned tiling -> mean tile probability aggregation"
                    )
                    coverage_note = "Edge-aligned starts ensure final row/column coverage."
                with st.expander("Explain", expanded=False):
                    st.markdown(
                        f"""
- **Model:** TensorFlow CNN classifier (`{MODEL_INPUT_SIZE[0]} x {MODEL_INPUT_SIZE[1]} x 3`)
- **Labels:** {", ".join(class_names)}
- **Dataset size:** approximately {DATASET_SIZE_APPROX:,} labeled images
- **Preprocessing strategy:** {strategy_desc}
- **Preprocessing mode:** `{st.session_state.get("landscape_preprocess_mode", "Legacy sparse tiling (original)")}`
- **Color mode:** `RGB`
- **Execution backend:** `{st.session_state.get("landscape_inference_backend", "CPU (stable)")}`
- **Coverage note:** {coverage_note}
                        """
                    )
                    d1, d2, d3 = st.columns(3)
                    d1.metric("Original image", f"{meta.original_width} x {meta.original_height}")
                    d2.metric("Processed image", f"{meta.resized_width} x {meta.resized_height}")
                    d3.metric("Model input", f"{meta.tile_size[1]} x {meta.tile_size[0]}")

                with st.expander("Performance", expanded=False):
                    perf_rows = [
                        {"Stage": "decode", "Time (ms)": timings["decode"]},
                        {"Stage": "preprocess", "Time (ms)": timings["preprocess"]},
                        {"Stage": "inference", "Time (ms)": timings["inference"]},
                        {"Stage": "postprocess", "Time (ms)": timings["postprocess"]},
                        {"Stage": "model_init (cached)", "Time (ms)": timings["model_init"]},
                    ]
                    perf_df = pd.DataFrame(perf_rows)
                    st.dataframe(
                        perf_df,
                        hide_index=True,
                        use_container_width=True,
                        column_config={"Time (ms)": st.column_config.NumberColumn(format="%.2f")},
                    )
                    st.markdown("**Tile vote distribution (argmax per tile)**")
                    st.dataframe(
                        pd.DataFrame(result["tile_vote_rows"]),
                        hide_index=True,
                        use_container_width=True,
                    )
                    p1, p2 = st.columns(2)
                    p1.metric("Mean tile max prob", f"{result['mean_tile_max']:.3f}")
                    p2.metric("Mean prediction entropy", f"{result['mean_entropy']:.3f}")
                    st.caption(
                        f"Tile count: {meta.tile_count} | overlap: {meta.overlap}px | strategy: {meta.strategy} | backend used: {result['applied_backend']} | batch shape: {result['batch_shape']}"
                    )
                with st.expander("Compatibility check (CPU stable)", expanded=False):
                    compat_df = st.session_state.get("landscape_compat_result")
                    if compat_df is None:
                        st.caption("Click “Run compatibility check (CPU, 2 modes)” to compare preprocessing paths.")
                    else:
                        st.dataframe(
                            compat_df,
                            hide_index=True,
                            use_container_width=True,
                            column_config={
                                "Confidence": st.column_config.NumberColumn(format="%.4f"),
                                "Entropy": st.column_config.NumberColumn(format="%.4f"),
                                "Tile max avg": st.column_config.NumberColumn(format="%.4f"),
                            },
                        )

    st.markdown("<div style='height: 0.75rem;'></div>", unsafe_allow_html=True)
