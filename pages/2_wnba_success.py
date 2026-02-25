import streamlit as st
import pandas as pd
from app.config import BASE_DIR, CREDS
from app.layout.header import page_header
from app.shared_ui import st_utils as stu
from lib.ops.memory import log_mem
from shared.settings import get_settings
import os
import time
import random
import json
from pathlib import Path
from bs4 import BeautifulSoup, Comment
from shared import utils
import requests
import re
import datetime
import html as html_lib
import numpy as np
from shared.telemetry import page_guard, track_submission


with page_guard(os.path.basename(__file__)):
    settings = get_settings()
    if settings.safe_mode:
        st.warning("Safe mode is enabled. This page is disabled to reduce memory usage.")
        st.stop()

    MODEL_PATH = os.path.join(
        BASE_DIR, "projects", "wnba_success", "model", "wnba_success_model.joblib"
    )
    FEATURE_SCHEMA_PATH = os.path.join(
        BASE_DIR, "projects", "wnba_success", "model", "feature_schema.json"
    )
    PDF_PATH = os.path.join(BASE_DIR, "projects", "wnba_success", "assets", "Predicting_WNBA_Success.pdf")
    ROOT_DIR = Path(__file__).resolve().parents[1]
    FIXTURES_DIR = ROOT_DIR / "projects" / "wnba_success" / "fixtures"
    OFFLINE_FIXTURE_PATH = FIXTURES_DIR / "offline_catalog.json"
    FORCE_OFFLINE = os.environ.get("WNBA_OFFLINE", "").lower() in ("1", "true", "yes", "y")
    REQUEST_TIMEOUT = 10

    BASE_URL = 'https://www.sports-reference.com'
    SEASON_URL_TEMPLATE = 'https://www.sports-reference.com/cbb/seasons/women/{}-school-stats.html'
    DISPLAY_FEATURES_FALLBACK = [
        "pg_fg%",
        "pg_2p%",
        "adv_efg%",
        "adv_ftr",
        "adv_drb%",
        "adv_obpm",
        "adv_bpm",
        "tot_fg%",
        "tot_2p%",
        "tot_blk",
    ]
    MODEL_FEATURES_FALLBACK = []
    FEATURE_NAME_MAP = {}
    COLLEGE_TEAM_ALIASES = {
        "middletennesseestate": "Middle Tennessee",
        "connecticut": "UConn",
    }
    CONFERENCE_ALIASES = {
        "americanathleticconference": "AAC",
        "atlanticcoastconference": "ACC",
        "bigtwelve": "Big 12",
        "big12conference": "Big 12",
        "bigeastconference": "Big East",
        "big10": "Big Ten",
        "bigtenconference": "Big Ten",
        "pac10conference": "Pac-10",
        "pac12conference": "Pac-12",
        "southeasternconference": "SEC",
    }
    AWARD_PATTERNS = {
        "All_Freshman_count": ("all-freshman", "all freshman"),
        "POY_count": ("player of the year", " poy "),
        "NCAA_Champion_count": ("ncaa champion", "national champion"),
        "NCAA_All_Tourney_count": ("ncaa all-tournament", "all-tournament"),
        "NCAA_All_Region_count": ("ncaa all-region", "all-region"),
        "Naismith_count": ("naismith",),
        "AP_count": ("associated press", " ap ", "ap all", "all-american"),
        "ROY_count": ("rookie of the year", " roy "),
        "DPOY_count": ("defensive player of the year", " dpoy "),
        "All_Defense_count": ("all-defensive", "all defense"),
        "MOP_count": ("most outstanding player", " mop "),
        "MIP_count": ("most improved player", " mip "),
    }
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": BASE_URL,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
    }
    MODEL_METADATA = {
        "success_cutoff": 22.425,
        "success_cutoff_label": "22.425 Win Shares (Top Quartile)",
        "success_definition": (
            "Elite is defined as reaching the top quartile of WNBA career Win Shares "
            "(≥ 22.425), representing sustained professional impact."
        ),
        "model_name": "Logistic Regression",
        "feature_cap": 20,
        "selection_method": "Cross-validated model search by ROC-AUC",
        "holdout_metrics": {
            "roc_auc": 0.945,
            "accuracy": 0.888,
            "precision": 0.857,
            "recall": 0.667,
        },
        "leakage_note": (
            "Pro-only outcome fields (including Win Share outcome variants) are excluded "
            "from model inputs."
        ),
    }

    @st.cache_data(ttl=3600, max_entries=2, show_spinner=False)
    def load_offline_catalog() -> dict:
        if not OFFLINE_FIXTURE_PATH.exists():
            return {}
        with open(OFFLINE_FIXTURE_PATH, "r") as handle:
            return json.load(handle)

    def _is_offline_mode() -> bool:
        return FORCE_OFFLINE or st.session_state.get("wnba_offline", False)

    def _enable_offline(reason: str) -> None:
        st.session_state["wnba_offline"] = True
        st.session_state["wnba_offline_reason"] = reason

    def _get_offline_team_urls(season=None) -> dict:
        catalog = load_offline_catalog()
        colleges = catalog.get("colleges", {})
        return {
            name: details.get("team_url", f"offline://{name.lower().replace(' ', '-')}")
            for name, details in colleges.items()
        }

    def _get_offline_player_urls(college: str) -> dict:
        catalog = load_offline_catalog()
        college_data = catalog.get("colleges", {}).get(college, {})
        players = college_data.get("players", {})
        return {
            name: details.get("player_url", f"offline://{name.lower().replace(' ', '-')}")
            for name, details in players.items()
        }

    def _get_offline_player_df(search_dict: dict) -> pd.DataFrame | None:
        catalog = load_offline_catalog()
        college_data = catalog.get("colleges", {}).get(search_dict.get("college", ""), {})
        player_data = college_data.get("players", {}).get(search_dict.get("player", ""))
        if not player_data:
            return None
        features = player_data.get("features", {}).copy()
        features["player_name"] = search_dict.get("player", "Unknown")
        return pd.DataFrame([features])

    def _get_offline_team_sos(college: str) -> float | None:
        catalog = load_offline_catalog()
        return catalog.get("colleges", {}).get(college, {}).get("team_sos")

    def _get_offline_seasons() -> list[int]:
        catalog = load_offline_catalog()
        season = catalog.get("season")
        return [season] if season else []


    def _patch_model_compat(model):
        try:
            from sklearn.compose import ColumnTransformer
        except Exception:
            return
        targets = []
        if isinstance(model, ColumnTransformer):
            targets.append(model)
        if hasattr(model, "named_steps"):
            for step in model.named_steps.values():
                if isinstance(step, ColumnTransformer):
                    targets.append(step)
        for transformer in targets:
            if not hasattr(transformer, "_name_to_fitted_passthrough"):
                transformer._name_to_fitted_passthrough = {}

    @st.cache_resource(show_spinner='Loading model...',ttl=43200)
    def init_model():
        log_mem("wnba_model_load:before")
        import joblib
        loaded_model = joblib.load(MODEL_PATH)
        _patch_model_compat(loaded_model)
        log_mem("wnba_model_load:after")

        # with open(MODEL_PATH, 'rb') as model_file:
        #     loaded_model = pickle.load(model_file)
        return loaded_model

    def _load_feature_schema_data():
        if not os.path.exists(FEATURE_SCHEMA_PATH):
            return None
        try:
            with open(FEATURE_SCHEMA_PATH, "r") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        return data

    def _load_feature_schema():
        data = _load_feature_schema_data()
        if data is None:
            return None
        if isinstance(data, list):
            return [str(item) for item in data]
        if isinstance(data, dict):
            for key in ("columns", "features", "feature_names", "model_features"):
                if key in data and isinstance(data[key], list):
                    return [str(item) for item in data[key]]
        return None

    def _dedupe_keep_order(values):
        seen = set()
        result = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def get_model_feature_names(model):
        if hasattr(model, "named_steps") and "preprocess" in model.named_steps:
            preprocess = model.named_steps["preprocess"]
            transformers = getattr(preprocess, "transformers_", None)
            if transformers:
                cols = []
                for name, _, col in transformers:
                    if name == "remainder":
                        continue
                    if isinstance(col, (list, tuple)):
                        cols.extend(list(col))
                    else:
                        try:
                            cols.extend(list(col))
                        except TypeError:
                            pass
                if cols:
                    return cols
            if hasattr(preprocess, "feature_names_in_"):
                return list(preprocess.feature_names_in_)
        schema = _load_feature_schema()
        if schema:
            return schema
        if hasattr(model, "feature_names_in_"):
            return list(model.feature_names_in_)
        named_steps = getattr(model, "named_steps", {})
        for step in named_steps.values():
            if hasattr(step, "feature_names_in_"):
                return list(step.feature_names_in_)
        return list(MODEL_FEATURES_FALLBACK)

    def get_display_feature_names(model, raw_feature_cols):
        if hasattr(model, "named_steps"):
            preprocess = model.named_steps.get("preprocess")
            selector = model.named_steps.get("feature_select")
            if (
                preprocess is not None
                and selector is not None
                and hasattr(preprocess, "get_feature_names_out")
                and hasattr(selector, "get_support")
            ):
                try:
                    transformed_names = list(preprocess.get_feature_names_out())
                    support_mask = selector.get_support()
                    if len(transformed_names) == len(support_mask):
                        selected = [
                            _strip_feature_prefix(name)
                            for name, selected_flag in zip(transformed_names, support_mask)
                            if selected_flag
                        ]
                        selected = _dedupe_keep_order(selected)
                        if selected:
                            return selected
                except Exception:
                    pass

        schema = _load_feature_schema_data()
        if isinstance(schema, dict) and isinstance(schema.get("selected_features"), list):
            selected = [_strip_feature_prefix(str(name)) for name in schema["selected_features"]]
            selected = _dedupe_keep_order(selected)
            if selected:
                return selected

        fallback = [col for col in DISPLAY_FEATURES_FALLBACK if col in raw_feature_cols]
        if fallback:
            return fallback
        return list(raw_feature_cols[:10])

    def get_success_label():
        schema = _load_feature_schema_data()
        if not isinstance(schema, dict):
            return "model-defined elite impact"
        meta = schema.get("target_metadata", {})
        source_col = meta.get("career_win_shares_source_column")
        threshold = meta.get("threshold")
        if source_col and threshold is not None:
            return f"{source_col} >= {threshold:.2f}"
        target_name = meta.get("target_column") or schema.get("target")
        if target_name:
            return str(target_name)
        return "model-defined elite impact"

    def _strip_feature_prefix(name: str) -> str:
        if "__" in name:
            return name.split("__", 1)[1]
        return name

    def _feature_names_prefixed(feature_cols: list[str]) -> bool:
        return bool(feature_cols) and all("__" in col for col in feature_cols)

    def _normalize_text(value: str) -> str:
        if not value:
            return ""
        cleaned = re.sub(r"[^a-z0-9]+", "", str(value).lower())
        return cleaned

    def _set_one_hot(model_input, col_name):
        if col_name and col_name in model_input.columns:
            model_input[col_name] = 1

    def _find_one_hot_column(columns, prefix, value):
        normalized_value = _normalize_text(value)
        if not normalized_value:
            return None
        for col in columns:
            if not str(col).startswith(prefix):
                continue
            suffix = str(col)[len(prefix) :]
            if _normalize_text(suffix) == normalized_value:
                return col
        return None

    def _extract_award_items(page_html):
        awards_list = page_html.find("ul", id="bling")
        if awards_list is None:
            return []
        return [li.get_text(" ", strip=True) for li in awards_list.find_all("li")]

    def _award_item_weight(text):
        if not text:
            return 0
        years = re.findall(r"\b(?:19|20)\d{2}\b", text)
        if years:
            return len(years)
        for pattern in (r"(?:x|×)\s*(\d+)", r"(\d+)\s*time"):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                try:
                    return max(int(match.group(1)), 1)
                except (TypeError, ValueError):
                    pass
        return 1

    def _award_feature_counts(award_items):
        feature_counts = {feature: 0 for feature in AWARD_PATTERNS}
        total_awards = 0
        for raw_item in award_items:
            text = f" {str(raw_item).lower()} "
            weight = _award_item_weight(text)
            if weight <= 0:
                continue
            total_awards += weight
            for feature_name, patterns in AWARD_PATTERNS.items():
                if any(pattern in text for pattern in patterns):
                    feature_counts[feature_name] += weight
        feature_counts["award_count"] = total_awards
        return feature_counts

    def _normalize_team_name(name):
        if name is None:
            return ""
        cleaned = (
            str(name)
            .replace("\xa0", " ")
            .replace("*", "")
            .replace("†", "")
            .replace("‡", "")
        )
        cleaned = re.sub(r"\s*\(.*?\)\s*", " ", cleaned)
        cleaned = re.sub(r"ncaa", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"[^a-z0-9]+", "", cleaned.lower())
        return cleaned

    def _extract_school_slug(team_url):
        if not team_url:
            return None
        match = re.search(r"/cbb/schools/([^/]+)/", team_url)
        if not match:
            return None
        return match.group(1)

    def _flatten_columns(columns):
        if not isinstance(columns, pd.MultiIndex):
            return [str(col) for col in columns]
        flat = []
        for col in columns:
            parts = [str(part).strip() for part in col if part and str(part).strip() != "nan"]
            flat.append(" ".join(parts))
        return flat

    def _extract_stat_from_meta(meta, label):
        if meta is None:
            return None
        def _normalize_number_text(text):
            return (
                text.replace("\u2212", "-")
                .replace("\u2013", "-")
                .replace("\u2014", "-")
            )

        def _extract_from_block(block):
            label_norm = label.strip().lower()
            for p in block.find_all("p"):
                strong = p.find("strong")
                if strong:
                    strong_text = strong.get_text(" ", strip=True).rstrip(":").strip().lower()
                    link = strong.find("a")
                    link_text = link.get_text(strip=True).lower() if link else ""
                    link_href = link.get("href", "").lower() if link else ""
                    if (
                        strong_text == label_norm
                        or link_text == label_norm
                        or f"#{label_norm}" in link_href
                    ):
                        tail_text = ""
                        for sibling in strong.next_siblings:
                            if isinstance(sibling, str):
                                tail_text += sibling
                            else:
                                tail_text += sibling.get_text(" ", strip=True)
                        tail_text = _normalize_number_text(tail_text)
                        match = re.search(r"[-\d\.]+", tail_text)
                        if match:
                            value = pd.to_numeric(match.group(0), errors="coerce")
                            if not pd.isna(value):
                                return float(value)
                        text = _normalize_number_text(p.get_text(" ", strip=True))
                        text = re.sub(
                            rf"^{re.escape(strong.get_text(strip=True))}\\s*", "", text
                        )
                        value = pd.to_numeric(text.split(" ")[0], errors="coerce")
                        if not pd.isna(value):
                            return float(value)
                else:
                    text = _normalize_number_text(p.get_text(" ", strip=True))
                    if re.search(rf"\\b{re.escape(label_norm)}\\b", text, re.IGNORECASE):
                        match = re.search(r"[-\d\\.]+", text)
                        if match:
                            value = pd.to_numeric(match.group(0), errors="coerce")
                            if not pd.isna(value):
                                return float(value)
            text = _normalize_number_text(block.get_text(" ", strip=True))
            match = re.search(
                rf"\\b{re.escape(label)}\\b\\s*[:=]\\s*([-\\d\\.]+)",
                text,
                re.IGNORECASE,
            )
            if match:
                value = pd.to_numeric(match.group(1), errors="coerce")
                if not pd.isna(value):
                    return float(value)
            return None

        value = _extract_from_block(meta)
        if value is not None:
            return value
        for comment in meta.find_all(string=lambda text: isinstance(text, Comment)):
            comment_soup = BeautifulSoup(str(comment), "lxml")
            value = _extract_from_block(comment_soup)
            if value is not None:
                return value
        return None

    def _find_meta_block(soup):
        meta = soup.find("div", id="meta") or soup.find("div", id="info")
        if meta is not None:
            return meta
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment_text = str(comment)
            if "id=\"meta\"" not in comment_text and "id='meta'" not in comment_text and "id=\"info\"" not in comment_text and "id='info'" not in comment_text:
                continue
            comment_soup = BeautifulSoup(comment_text, "lxml")
            meta = comment_soup.find("div", id="meta") or comment_soup.find("div", id="info")
            if meta is not None:
                return meta
        return None

    def _extract_stat_from_html(html, label):
        if not html:
            return None
        html_norm = html_lib.unescape(html)
        html_norm = (
            html_norm.replace("\u2212", "-")
            .replace("\u2013", "-")
            .replace("\u2014", "-")
        )
        patterns = [
            rf"#{label.lower()}[^>]*>.*?</a>\s*:\s*</strong>\s*([-\d\.]+)",
            rf">{re.escape(label)}\s*</a>\s*:\s*</strong>\s*([-\d\.]+)",
            rf">{re.escape(label)}\s*</strong>\s*:\s*([-\d\.]+)",
            rf"{re.escape(label)}\s*:\s*</strong>\s*([-\d\.]+)",
            rf"{re.escape(label)}[^0-9\-]*([-\d\.]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, html_norm, re.IGNORECASE | re.DOTALL)
            if match:
                value = pd.to_numeric(match.group(1), errors="coerce")
                if not pd.isna(value):
                    return float(value)
        return None

    def _get_team_page_sos(team_url):
        if not team_url:
            return None
        headers = dict(DEFAULT_HEADERS)
        response = requests.get(team_url, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.content, "lxml")
        meta = _find_meta_block(soup)
        if meta is None:
            # Last-ditch regex parse on raw HTML.
            sos = _extract_stat_from_html(response.text, "SOS")
            if sos is not None:
                return sos
            srs = _extract_stat_from_html(response.text, "SRS")
            if srs is not None:
                return srs
            return None
        sos = _extract_stat_from_meta(meta, "SOS")
        if sos is not None:
            return sos
        srs = _extract_stat_from_meta(meta, "SRS")
        if srs is not None:
            return srs
        sos = _extract_stat_from_html(response.text, "SOS")
        if sos is not None:
            return sos
        srs = _extract_stat_from_html(response.text, "SRS")
        if srs is not None:
            return srs
        return None

    @st.cache_data(ttl=43200, max_entries=128, show_spinner=False)
    def get_team_sos(season, college, team_url=None):
        if team_url:
            team_page_sos = _get_team_page_sos(team_url)
            if team_page_sos is not None:
                return team_page_sos

        headers = dict(DEFAULT_HEADERS)
        season_url = SEASON_URL_TEMPLATE.format(season)
        response = requests.get(season_url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "lxml")
        table = soup.find("table", id="school_stats")
        if table is None:
            table = _find_table_in_comments(soup, ["school_stats"], "school stats")
        if table is not None:
            slug = _extract_school_slug(team_url)
            rows = table.tbody.find_all("tr") if table.tbody else table.find_all("tr")
            for row in rows:
                if "class" in row.attrs and "thead" in row.attrs.get("class", []):
                    continue
                school_cell = row.find("th", {"data-stat": "school_name"}) or row.find(
                    "th", {"data-stat": "school"}
                )
                if school_cell is None:
                    school_cell = row.find("td", {"data-stat": "school_name"}) or row.find(
                        "td", {"data-stat": "school"}
                    )
                if school_cell is None:
                    continue
                link = school_cell.find("a")
                href = link.get("href", "") if link else ""
                school_name = school_cell.get_text(strip=True)
                if slug and slug in href:
                    sos_cell = (
                        row.find("td", {"data-stat": "sos"})
                        or row.find("td", {"data-stat": "srs"})
                        or row.find("td", {"data-stat": "strength_of_schedule"})
                    )
                    if sos_cell is None:
                        continue
                    value = pd.to_numeric(sos_cell.get_text(strip=True), errors="coerce")
                    if pd.isna(value):
                        return None
                    return float(value)

            # Fallback to name match if slug match failed.
            target = _normalize_team_name(college)
            for row in rows:
                if "class" in row.attrs and "thead" in row.attrs.get("class", []):
                    continue
                school_cell = row.find("th", {"data-stat": "school_name"}) or row.find(
                    "th", {"data-stat": "school"}
                )
                if school_cell is None:
                    school_cell = row.find("td", {"data-stat": "school_name"}) or row.find(
                        "td", {"data-stat": "school"}
                    )
                if school_cell is None:
                    continue
                school_name = school_cell.get_text(strip=True)
                if _normalize_team_name(school_name) != target:
                    continue
                sos_cell = (
                    row.find("td", {"data-stat": "sos"})
                    or row.find("td", {"data-stat": "srs"})
                    or row.find("td", {"data-stat": "strength_of_schedule"})
                )
                if sos_cell is None:
                    return None
                value = pd.to_numeric(sos_cell.get_text(strip=True), errors="coerce")
                if pd.isna(value):
                    return None
                return float(value)

        # Last-resort fallback to read_html with name matching (no hrefs)
        tables = pd.read_html(response.text)
        df = None
        for candidate in tables:
            if "School" in candidate.columns:
                df = candidate
                break
        else:
            return None

        school_col = "School" if "School" in df.columns else None
        if school_col is None:
            return None

        flat_cols = _flatten_columns(df.columns)
        df.columns = flat_cols
        sos_col = None
        for col in df.columns:
            col_norm = str(col).strip().lower()
            if col_norm == "sos" or "strength of schedule" in col_norm:
                sos_col = col
                break
        if sos_col is None:
            for col in df.columns:
                col_norm = str(col).strip().lower()
                if col_norm == "srs":
                    sos_col = col
                    break
        if sos_col is None:
            return None

        target = _normalize_team_name(college)
        df["_school_norm"] = df[school_col].apply(_normalize_team_name)
        match = df[df["_school_norm"] == target]
        if match.empty:
            return None
        value = pd.to_numeric(match[sos_col].iloc[0], errors="coerce")
        if pd.isna(value):
            return None
        return float(value)

    def build_model_input(base_df, model, search_dict):
        if base_df is None or base_df.empty:
            return None, None, None, None
        feature_cols = get_model_feature_names(model)
        raw_feature_cols = [_strip_feature_prefix(col) for col in feature_cols]
        features = base_df.rename(columns=FEATURE_NAME_MAP).copy()
        if "adv_per_college" not in features.columns and "adv_per" in features.columns:
            features["adv_per_college"] = features["adv_per"]
        if "adv_efg%" not in features.columns:
            if all(col in features.columns for col in ("pg_fg", "pg_3p", "pg_fga")):
                denom = pd.to_numeric(features["pg_fga"], errors="coerce")
                numer = (
                    pd.to_numeric(features["pg_fg"], errors="coerce")
                    + 0.5 * pd.to_numeric(features["pg_3p"], errors="coerce")
                )
                features["adv_efg%"] = numer / denom.replace(0, np.nan)
            elif all(col in features.columns for col in ("tot_fg", "tot_3p", "tot_fga")):
                denom = pd.to_numeric(features["tot_fga"], errors="coerce")
                numer = (
                    pd.to_numeric(features["tot_fg"], errors="coerce")
                    + 0.5 * pd.to_numeric(features["tot_3p"], errors="coerce")
                )
                features["adv_efg%"] = numer / denom.replace(0, np.nan)

        model_input = pd.DataFrame(index=features.index)
        for col in raw_feature_cols:
            if col in features.columns:
                model_input[col] = features[col]
            else:
                model_input[col] = np.nan

        college_value = search_dict.get("college") if search_dict else None
        if college_value:
            normalized_college = _normalize_text(college_value)
            college_col = _find_one_hot_column(
                model_input.columns, "college_team_", college_value
            )
            if college_col is None:
                college_alias = COLLEGE_TEAM_ALIASES.get(normalized_college)
                if college_alias:
                    college_col = _find_one_hot_column(
                        model_input.columns, "college_team_", college_alias
                    )
            _set_one_hot(model_input, college_col)

        conf_value = None
        for col in ("pg_conf", "adv_conf", "tot_conf"):
            if col in features.columns and features[col].notna().any():
                conf_value = str(features[col].iloc[0])
                break
        if conf_value:
            normalized_conf = _normalize_text(conf_value)
            conf_col = _find_one_hot_column(model_input.columns, "conference_", conf_value)
            if conf_col is None:
                conf_alias = CONFERENCE_ALIASES.get(normalized_conf)
                if conf_alias:
                    conf_col = _find_one_hot_column(
                        model_input.columns, "conference_", conf_alias
                    )
            _set_one_hot(model_input, conf_col)

        for col in model_input.columns:
            if col.startswith("college_team_") or col.startswith("conference_"):
                model_input[col] = model_input[col].fillna(0)
        model_input = model_input.apply(pd.to_numeric, errors="coerce")

        display_target_cols = get_display_feature_names(model, raw_feature_cols)
        display_cols = [col for col in display_target_cols if col in model_input.columns]
        if not display_cols:
            st.error(
                "No feature columns available for display. "
                "Check feature schema and model artifact compatibility."
            )
            return None, None, None, None
        display_df = model_input[display_cols].copy()
        return model_input, display_df, display_cols, raw_feature_cols

    def _confidence_band(probability: float) -> str:
        if probability < 0.40:
            return "Low"
        if probability <= 0.70:
            return "Medium"
        return "High"

    def _score_with_feature_names(model, model_input):
        if not hasattr(model, "named_steps"):
            return None, None, None
        preprocess = model.named_steps.get("preprocess")
        estimator = model.named_steps.get("model")
        if preprocess is None or estimator is None:
            return None, None, None
        if not hasattr(preprocess, "transform") or not hasattr(estimator, "coef_"):
            return None, None, None
        try:
            transformed = preprocess.transform(model_input)
            feature_names = (
                list(preprocess.get_feature_names_out())
                if hasattr(preprocess, "get_feature_names_out")
                else []
            )
            selector = model.named_steps.get("feature_select")
            if selector is not None and hasattr(selector, "get_support"):
                support = selector.get_support()
                if feature_names and len(feature_names) == len(support):
                    feature_names = [name for name, keep in zip(feature_names, support) if keep]
                transformed = selector.transform(transformed)
            if hasattr(transformed, "toarray"):
                transformed = transformed.toarray()
            transformed = np.asarray(transformed)
            if transformed.ndim != 2 or transformed.shape[0] == 0:
                return None, None, None
            if not feature_names:
                feature_names = [f"feature_{idx}" for idx in range(transformed.shape[1])]
            coefs = np.asarray(estimator.coef_)[0]
            if len(feature_names) != len(coefs) or transformed.shape[1] != len(coefs):
                return None, None, None
            return transformed[0], coefs, feature_names
        except Exception:
            return None, None, None

    def get_player_feature_contributions(model, model_input, top_n=8):
        values, coefs, feature_names = _score_with_feature_names(model, model_input)
        if values is None:
            return None
        contributions = values * coefs
        contrib_df = pd.DataFrame(
            {
                "feature": [_strip_feature_prefix(str(name)) for name in feature_names],
                "contribution": contributions,
                "coef": coefs,
                "feature_value": values,
            }
        )
        positive = contrib_df[contrib_df["contribution"] > 0].sort_values(
            "contribution", ascending=False
        )
        negative = contrib_df[contrib_df["contribution"] < 0].sort_values("contribution")
        if positive.empty and negative.empty:
            return None
        return {
            "mode": "player_specific",
            "positive": positive.head(top_n).reset_index(drop=True),
            "negative": negative.head(top_n).reset_index(drop=True),
        }

    def get_global_top_coefficients(model, top_n=10):
        if not hasattr(model, "named_steps"):
            return None
        preprocess = model.named_steps.get("preprocess")
        estimator = model.named_steps.get("model")
        if preprocess is None or estimator is None or not hasattr(estimator, "coef_"):
            return None
        feature_names = (
            list(preprocess.get_feature_names_out())
            if hasattr(preprocess, "get_feature_names_out")
            else []
        )
        selector = model.named_steps.get("feature_select")
        if selector is not None and hasattr(selector, "get_support") and feature_names:
            support = selector.get_support()
            if len(feature_names) == len(support):
                feature_names = [name for name, keep in zip(feature_names, support) if keep]
        coefs = np.asarray(estimator.coef_)[0]
        if not feature_names or len(feature_names) != len(coefs):
            feature_names = [f"feature_{idx}" for idx in range(len(coefs))]
        coef_df = pd.DataFrame(
            {
                "feature": [_strip_feature_prefix(str(name)) for name in feature_names],
                "coef": coefs,
            }
        )
        coef_df["abs_coef"] = coef_df["coef"].abs()
        coef_df = coef_df.sort_values("abs_coef", ascending=False).head(top_n)
        return coef_df[["feature", "coef"]].reset_index(drop=True)


    # Load the model from the file

    def get_player_url(search_dict):
        # Constructing the Google search URL
        user_agent = random.choice(utils.user_agents) 
        headers = {'User-Agent': user_agent} 

        query = f"{search_dict['player']} college stats sports-reference women's basketball"
        # query = f"{player} college stats sports-reference women's basketball {row['college_team']}"

        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        link_url = None

        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')

            # Locate the first link with "sports-reference.com" in its href attribute
            link = soup.find('a', href=lambda x: x and "www.sports-reference.com/cbb/players/" in x)

            if link:
                # Extract the desired URL using regular expression
                match = re.search(r'(https://www.sports-reference.com/.*?\.html)', link['href'])
                if match:
                    link_url = match.group(1)
                    print(f"For {search_dict['player']} from {search_dict['college']}, stats link: {link_url}")
                else:
                    print(f"No desired pattern found in link for {search_dict['player']} from {search_dict['college']}")
            else:
                print(f"No link found for {search_dict['player']} from {search_dict['college']}")
                print(f"No link found for {search_dict['player']} from {search_dict['college']}")

        else:
            print(f"Failed to fetch search results for {search_dict['player']} from {search_dict['college']}")
        time.sleep(5)
        return link_url
        # To avoid making too many rapid requests, sleep for a few seconds between searches

    def _find_table_in_comments(soup, table_ids, header_text):
        header_text = (header_text or "").lower()
        table_ids = table_ids or []
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment_text = str(comment).lower()
            if header_text and header_text not in comment_text and not any(tid in comment_text for tid in table_ids):
                continue
            comment_soup = BeautifulSoup(comment, "lxml")
            for table_id in table_ids:
                table = comment_soup.find("table", id=table_id)
                if table is not None:
                    return table
            table = comment_soup.find("table")
            if table is not None:
                return table
        return None

    def _find_stats_table(soup, header_text, table_ids=None):
        header_text = (header_text or "").strip()
        header_text_lower = header_text.lower()

        h2_tag = soup.find(
            lambda tag: tag.name in ("h2", "h3")
            and tag.get_text(strip=True).lower() == header_text_lower
        )
        if h2_tag is None:
            h2_tag = soup.find(
                lambda tag: tag.name in ("h2", "h3")
                and header_text_lower in tag.get_text(strip=True).lower()
            )

        table = h2_tag.find_next("table") if h2_tag is not None else None

        if table is None and table_ids:
            for table_id in table_ids:
                table = soup.find("table", id=table_id)
                if table is not None:
                    break

        if table is None:
            table = _find_table_in_comments(soup, table_ids, header_text_lower)

        return table

    def _table_to_df(table):
        if table is None:
            return None
        try:
            return pd.read_html(str(table))[0]
        except ValueError:
            return None

    def get_player_df(search_dict):
        if _is_offline_mode():
            return _get_offline_player_df(search_dict)
        # player_url = get_player_url(search_dict)
        player_url = BASE_URL + search_dict['player_url']
        session = requests.session()
        user_agent = random.choice(utils.user_agents) 
        headers = {'User-Agent': user_agent} 

        try:
            response = session.get(player_url, headers = headers, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            _enable_offline(f"Network unavailable: {exc}")
            return _get_offline_player_df(search_dict)
        # response = session.get(player_url)
        if response.status_code != 200:
            print(response.status_code)
        else:
            pass


        page_html = BeautifulSoup(response.text, 'html5lib')
        award_items = _extract_award_items(page_html)
        award_feature_counts = _award_feature_counts(award_items)
        awards,name,position,height = utils.extract_details_from_page(page_html)

        div_class = page_html.findAll('h1')
        player_name = div_class[0].find('span').text

        prefixes = {'adv_': 'Advanced', 'pg_': 'Per Game', 'tot_': 'Totals'}
        # Initialize an empty dictionary to hold dataframes
        dataframes = {}

        soup = BeautifulSoup(response.content, 'lxml')

        missing_sections = []
        adv_table = _find_stats_table(soup, "Advanced", table_ids=["players_advanced", "advanced"])
        player_adv_df = _table_to_df(adv_table)
        if player_adv_df is None:
            missing_sections.append("Advanced")
        else:
            dataframes["adv_"] = player_adv_df.add_prefix("adv_")

        pg_table = _find_stats_table(soup, "Per Game", table_ids=["players_per_game", "per_game"])
        player_pg_df = _table_to_df(pg_table)
        if player_pg_df is None:
            missing_sections.append("Per Game")
        else:
            dataframes["pg_"] = player_pg_df.add_prefix("pg_")

        tot_table = _find_stats_table(soup, "Totals", table_ids=["players_totals", "totals"])
        player_tot_df = _table_to_df(tot_table)
        if player_tot_df is None:
            missing_sections.append("Totals")
        else:
            dataframes["tot_"] = player_tot_df.add_prefix("tot_")

        if missing_sections:
            st.error(
                "Stats tables missing on Sports-Reference for "
                f"{search_dict.get('player', 'this player')}: "
                + ", ".join(missing_sections)
                + ". Try a different player or season."
            )
            return None

        # Perform merging
        base_df = dataframes['pg_'].merge(dataframes['adv_'], how='left', left_on='pg_Season', right_on='adv_Season')
        base_df = base_df.merge(dataframes['tot_'], how='left', left_on='pg_Season', right_on='tot_Season')
        base_df['player_name'] =player_name
        base_df['position'] =position
        base_df['height'] =height
        base_df['awards'] =awards
        for award_feature, award_value in award_feature_counts.items():
            base_df[award_feature] = award_value
        # base_df.to_csv('ncaa_ref/' + player_name + '.csv')
        base_df = prep_df(base_df)

        return base_df

    def prep_df(df):
        # Convert column names to lowercase
        df.rename(columns={'adv_per_x': 'adv_per_college','adv_per_y':'per_pro','adv_ws/48':'ws_48_pro','player_name_x':'player_name'}, inplace=True)
        df.columns = df.columns.str.lower()

        # Remove columns with 'unnamed' in their names
        df = df.loc[:, ~df.columns.str.contains('unnamed', case=False)]
        df = df[df['pg_season'] == 'Career']
        return df


    import base64

    @st.cache_data(show_spinner=False, max_entries=4)
    def load_pdf_bytes(file_path: str) -> bytes:
        log_mem("wnba_pdf_download:before")
        with open(file_path, "rb") as handle:
            data = handle.read()
        log_mem("wnba_pdf_download:after")
        return data

    # UI refactor note: page presentation is split into render_* functions while keeping
    # existing scrape/build/predict behavior unchanged.
    def render_header():
        page_header(
            "WNBA Elite Impact Projection",
            page_name=os.path.basename(__file__),
        )
        st.caption(
            "Given an NCAA season and player, estimate likelihood they will reach elite WNBA "
            "career impact measured by top-quartile Win Shares."
        )

    def _card_container():
        try:
            return st.container(border=True)
        except TypeError:
            return st.container()

    @st.cache_data(ttl=42300, max_entries=50, show_spinner=False)
    def get_team_urls(year=2023):

        user_agent = random.choice(utils.user_agents) 
        headers = {'User-Agent': user_agent} 
        season_url = SEASON_URL_TEMPLATE.format(year)
        response = requests.get(season_url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html5lib')
        url_dict = utils.get_url_dict(soup)

        return {key: BASE_URL + val for key, val in url_dict.items() if f'/women/{year}' in val and '/cbb/schools/' in val}

    @st.cache_data(ttl=42300, max_entries=200, show_spinner=False)
    def get_player_urls(team_url):
        user_agent = random.choice(utils.user_agents) 
        headers = {'User-Agent': user_agent} 

        response = requests.get(team_url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'lxml')
        h2_tag = soup.find('h2', string='Roster')
        table = h2_tag.find_next('table')
        return utils.get_url_dict(table)

    def get_team_urls_safe(year=2023) -> dict:
        if _is_offline_mode():
            return _get_offline_team_urls(year)
        try:
            return get_team_urls(year)
        except requests.RequestException as exc:
            _enable_offline(f"Network unavailable: {exc}")
            return _get_offline_team_urls(year)

    def get_player_urls_safe(team_url: str, college: str) -> dict:
        if _is_offline_mode():
            return _get_offline_player_urls(college)
        try:
            return get_player_urls(team_url)
        except requests.RequestException as exc:
            _enable_offline(f"Network unavailable: {exc}")
            return _get_offline_player_urls(college)

    def get_team_sos_safe(season, college, team_url=None):
        if _is_offline_mode():
            return _get_offline_team_sos(college)
        try:
            return get_team_sos(season, college, team_url)
        except requests.RequestException as exc:
            _enable_offline(f"Network unavailable: {exc}")
            return _get_offline_team_sos(college)

    def render_controls():
        search_dict = {}
        with _card_container():
            st.markdown("#### Player Selection")
            c1, c2, c3 = st.columns(3)
            with c1:
                current_year = datetime.datetime.now().year
                if _is_offline_mode():
                    seasons = _get_offline_seasons() or [current_year]
                else:
                    seasons = list(range(current_year - 19, current_year + 1))
                    seasons.sort(reverse=True)
                search_dict["season"] = st.selectbox(
                    "Season",
                    options=seasons,
                    key="wnba_season",
                )

            team_urls = get_team_urls_safe(search_dict["season"])
            if not team_urls:
                st.error("No team data available. Check network access or offline fixtures.")
                st.stop()
            colleges = sorted(team_urls.keys())

            with c2:
                search_dict["college"] = st.selectbox(
                    "College",
                    options=colleges,
                    key="wnba_college",
                )

            search_dict["team_url"] = team_urls[search_dict["college"]]
            player_dict = get_player_urls_safe(search_dict["team_url"], search_dict["college"])
            if not player_dict:
                st.error("No player data available for this team. Check fixtures or network.")
                st.stop()
            players = sorted(player_dict.keys())

            with c3:
                search_dict["player"] = st.selectbox(
                    "Player",
                    options=players,
                    key="wnba_player",
                )
            search_dict["player_url"] = player_dict[search_dict["player"]]

            b1, b2 = st.columns([1, 2])
            with b1:
                predict_clicked = st.button(
                    "Estimate Elite Potential", type="primary", key="wnba_predict"
                )
            with b2:
                st.caption("How to interpret: see the “How it works” section below this result.")

        return search_dict, predict_clicked

    def _safe_probability(model, model_input):
        if hasattr(model, "predict_proba"):
            try:
                return float(model.predict_proba(model_input)[0, 1])
            except Exception:
                pass
        if hasattr(model, "decision_function"):
            try:
                score = float(model.decision_function(model_input)[0])
                return float(1.0 / (1.0 + np.exp(-score)))
            except Exception:
                pass
        return None

    def run_prediction(search_dict):
        with st.spinner("Running model..."):
            log_mem("wnba_predict:before_data")
            base_df = get_player_df(search_dict)
            log_mem("wnba_predict:after_data")
            if base_df is None or base_df.empty:
                return None

            log_mem("wnba_predict:before_model")
            model = init_model()
            log_mem("wnba_predict:after_model")
            model_input, display_df, display_cols, model_cols = build_model_input(
                base_df, model, search_dict
            )
            if model_input is None:
                return None

            predicted_value = int(model.predict(model_input)[0])
            probability = _safe_probability(model, model_input)
            if probability is None:
                probability = 0.65 if predicted_value == 1 else 0.35

            attribution = get_player_feature_contributions(model, model_input, top_n=8)
            if attribution is None:
                global_coef = get_global_top_coefficients(model, top_n=10)
                attribution = (
                    {"mode": "global", "global": global_coef}
                    if global_coef is not None
                    else {"mode": "unavailable"}
                )

            validation_df = pd.DataFrame(
                {"feature": display_cols, "raw_value": display_df.iloc[0].values}
            )
            st.session_state["validation_df"] = validation_df
            st.session_state["validation_meta"] = {
                "model_features": len(model_cols),
                "used_features": len(display_cols),
            }

            return {
                "player_name": str(base_df["player_name"].iloc[0]),
                "inputs": search_dict.copy(),
                "predicted_value": predicted_value,
                "probability": float(probability),
                "confidence_band": _confidence_band(float(probability)),
                "display_df": display_df,
                "display_cols": display_cols,
                "attribution": attribution,
            }

    def _contribution_table(df: pd.DataFrame, descending=True):
        table = df.copy()
        table = table.sort_values("contribution", ascending=not descending)
        max_abs = float(table["contribution"].abs().max()) if not table.empty else 0.0
        if max_abs <= 0:
            table["impact"] = ""
        else:
            table["impact"] = table["contribution"].apply(
                lambda v: ("+" if v >= 0 else "-")
                + ("#" * max(1, int(round((abs(v) / max_abs) * 12))))
            )
        table["contribution"] = table["contribution"].map(lambda v: round(float(v), 3))
        table["feature_value"] = table["feature_value"].map(lambda v: round(float(v), 3))
        table["coef"] = table["coef"].map(lambda v: round(float(v), 3))
        return table[["feature", "impact", "contribution", "feature_value", "coef"]]

    def render_prediction(result):
        with _card_container():
            st.markdown("### Prediction")
            st.markdown(
                f"## Estimated Elite Impact Likelihood: {result['probability']:.0%}"
            )
            st.progress(int(max(0.0, min(1.0, result["probability"])) * 100))

            pcol1, pcol2, pcol3 = st.columns([1, 1, 2])
            pcol1.metric("Player", result["player_name"])
            pcol2.metric("Confidence band", result["confidence_band"])
            pcol3.metric(
                "Elite label",
                "Elite Tier" if result["predicted_value"] == 1 else "Not Elite Tier",
            )

            st.info(
                "This estimate is based on college-era features only. "
                f"{MODEL_METADATA['success_definition']} "
                "Use the output as a probabilistic signal, not a guarantee."
            )

            st.caption(
                f"Last run: {result['inputs']['season']} • {result['inputs']['college']} • "
                f"{result['inputs']['player']}"
            )

            with st.expander("Features used for this prediction", expanded=False):
                st.dataframe(result["display_df"], hide_index=True, use_container_width=True)

            with st.expander("What drove this prediction?", expanded=False):
                attr = result.get("attribution", {})
                if attr.get("mode") == "player_specific":
                    st.caption(
                        "Player-specific contribution view (using transformed features): contribution = coefficient × feature value."
                    )
                    left, right = st.columns(2)
                    with left:
                        st.markdown("**Top Positive Contributors**")
                        st.dataframe(
                            _contribution_table(attr["positive"], descending=True),
                            hide_index=True,
                            use_container_width=True,
                        )
                    with right:
                        st.markdown("**Top Negative Contributors**")
                        st.dataframe(
                            _contribution_table(attr["negative"], descending=False),
                            hide_index=True,
                            use_container_width=True,
                        )
                elif attr.get("mode") == "global" and attr.get("global") is not None:
                    st.caption(
                        "Player-specific attribution is unavailable for this run; showing global coefficient magnitude instead."
                    )
                    st.dataframe(attr["global"], hide_index=True, use_container_width=True)
                else:
                    st.caption("Feature attribution is unavailable for the current model artifact.")

    def render_paper_tab():
        st.info(
            "The app's model may be updated from the version described in the paper."
        )
        st.write(
            "The paper documents the original problem framing, feature design choices, and "
            "evaluation approach used in early iterations of this project."
        )
        st.write(
            "Use it for methodology context; the live app reflects the current deployed model artifact."
        )

        pdf_bytes = load_pdf_bytes(PDF_PATH)
        st.download_button(
            label="Download Paper",
            data=pdf_bytes,
            file_name="Predicting_WNBA_Success.pdf",
            mime="application/pdf",
            key="submit_wnba_download",
        )

        log_mem("wnba_pdf:before")
        encoded_pdf = base64.b64encode(pdf_bytes).decode("utf-8")
        log_mem("wnba_pdf:after")
        st.markdown(
            f'<embed src="data:application/pdf;base64,{encoded_pdf}" width="100%" height="560" type="application/pdf">',
            unsafe_allow_html=True,
        )

    def render_model_tabs():
        tab_how, tab_data, tab_perf, tab_faq, tab_paper = st.tabs(
            ["How it works", "Data + Leakage", "Model Performance", "FAQ", "Paper"]
        )

        with tab_how:
            st.markdown("1. Choose a season, college, and player (NCAA context).")
            st.markdown("2. Build that player's NCAA feature vector from scraped stats/context.")
            st.markdown("3. Apply training-time preprocessing: missing-value handling, scaling, and one-hot encoding.")
            st.markdown("4. Keep the 20 most informative features from the selected feature set.")
            st.markdown("5. Run the trained model to estimate elite impact likelihood.")
            st.markdown("**What this is**")
            st.markdown("- A statistical estimate based on historical NCAA-to-WNBA patterns.")
            st.markdown(
                "- A comparison tool for pre-pro profiles under a consistent elite impact tier definition."
            )
            st.markdown("**What this isn't**")
            st.markdown("- Not a scouting report or medical projection.")
            st.markdown("- Not a guarantee of future outcomes for any single player.")

        with tab_data:
            st.write(
                "Training data links historical NCAA player profiles to eventual WNBA outcomes."
            )
            st.write(
                "Inputs are pre-pro features: college performance and context (conference, team, position, and related profile fields)."
            )
            st.write(MODEL_METADATA["leakage_note"])
            st.warning(
                "Not a guarantee: this is a statistical estimate from historical patterns."
            )

        with tab_perf:
            perf = MODEL_METADATA["holdout_metrics"]
            snap1, snap2 = st.columns(2)
            snap1.metric("Elite impact cutoff", f"{MODEL_METADATA['success_cutoff']:.3f}")
            snap1.caption("Win Shares (Top Quartile)")
            snap2.metric("Model", MODEL_METADATA["model_name"])
            snap3, snap4 = st.columns(2)
            snap3.metric("ROC-AUC", f"{perf['roc_auc']:.3f}")
            snap4.metric("Features", f"{MODEL_METADATA['feature_cap']}")
            snap4.caption("Selected")
            pc1, pc2, pc3 = st.columns(3)
            pc1.metric("Accuracy", f"{perf['accuracy']:.3f}")
            pc2.metric("Precision", f"{perf['precision']:.3f}")
            pc3.metric("Recall", f"{perf['recall']:.3f}")
            st.caption(
                "Recall is lower than precision because with class imbalance and a fixed classification threshold, "
                "the model is more conservative in calling positives."
            )
            st.caption(
                "Model selection used cross-validated search across model families and selected the best ROC-AUC."
            )
            st.caption(
                f"Latest retrain uses a {MODEL_METADATA['feature_cap']}-feature cap and selected "
                f"{MODEL_METADATA['model_name']}."
            )

        with tab_faq:
            faq_items = [
                (
                    "What does ‘Elite Career Impact’ mean?",
                    "This model estimates the likelihood a player reaches the top quartile of WNBA career Win Shares "
                    "(currently ≥ 22.425). That threshold represents sustained, high-level professional impact, not "
                    "whether someone is ‘successful’ at basketball.",
                ),
                (
                    "Why only college-era features?",
                    "The model uses only pre-pro information (college performance and context like team, conference, "
                    "and position). Pro-career outcome fields, including Win Shares, are excluded from the inputs to "
                    "keep the prediction forward-looking.",
                ),
                (
                    "How should I interpret the probability?",
                    "A 70% estimate means that, historically, players with similar college profiles reached "
                    "top-quartile WNBA career impact about 70% of the time. It’s a statistical estimate, not a guarantee.",
                ),
                (
                    "How good is the model?",
                    "On a held-out evaluation set, the current retrained model (logistic regression, 20 selected "
                    "features) reports:\n"
                    "• ROC-AUC: 0.945\n"
                    "• Accuracy: 0.888\n"
                    "• Precision: 0.857\n"
                    "• Recall: 0.667",
                ),
                (
                    "Why not call this ‘success’?",
                    "Making the WNBA is already an achievement. This model is specifically about the likelihood of "
                    "reaching an elite tier of career impact, not judging whether someone is ‘successful’.",
                ),
            ]
            for question, answer in faq_items:
                with st.expander(question):
                    st.write(answer)

        with tab_paper:
            render_paper_tab()

    if "validation_df" not in st.session_state:
        st.session_state["validation_df"] = None
    if "validation_meta" not in st.session_state:
        st.session_state["validation_meta"] = None
    if "wnba_prediction_result" not in st.session_state:
        st.session_state["wnba_prediction_result"] = None

    render_header()

    if _is_offline_mode():
        reason = st.session_state.get("wnba_offline_reason")
        st.warning("Offline mode enabled. Using fixture data for predictions.")
        if reason:
            st.caption(reason)
        st.caption("Set WNBA_OFFLINE=1 to force offline mode.")

    search_dict, predict_clicked = render_controls()
    if predict_clicked:
        inputs = {
            "season": search_dict.get("season"),
            "college": search_dict.get("college"),
            "player": search_dict.get("player"),
            "offline_mode": _is_offline_mode(),
            "data_source": "offline" if _is_offline_mode() else "live",
        }
        try:
            track_submission(
                page_id="wnba_success",
                form_id="predict",
                inputs=inputs,
                tags={"feature": "predict"},
            )
        except Exception:
            pass
        prediction_result = run_prediction(search_dict)
        if prediction_result is not None:
            st.session_state["wnba_prediction_result"] = prediction_result

    if st.session_state["wnba_prediction_result"] is not None:
        render_prediction(st.session_state["wnba_prediction_result"])

    stu.V_SPACE(1)
    render_model_tabs()
