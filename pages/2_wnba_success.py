import streamlit as st
import pandas as pd
from app.config import BASE_DIR, CREDS
from app.layout.header import page_header
from app.shared_ui import st_utils as stu
import os
import time
import random
import json
from pathlib import Path
from bs4 import BeautifulSoup, Comment
from shared import utils
import requests
import re
import joblib
import datetime
import html as html_lib
from shared.telemetry import page_guard


with page_guard(os.path.basename(__file__)):
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
    MODEL_FEATURES_FALLBACK = [
        "pg_2p_pct",
        "adv_stl_pct",
        "pg_fg_pct",
        "pg_pts",
        "pg_sos",
        "adv_trb_pct",
        "adv_ast_pct",
        "pg_tov",
    ]
    FEATURE_NAME_MAP = {
        "pg_2p%": "pg_2p_pct",
        "adv_stl%": "adv_stl_pct",
        "pg_fg%": "pg_fg_pct",
        "adv_trb%": "adv_trb_pct",
        "adv_ast%": "adv_ast_pct",
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

    @st.cache_data(show_spinner=False)
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


    @st.cache_resource(show_spinner='Loading model...',ttl=43200)
    def init_model():
        loaded_model = joblib.load(MODEL_PATH)

        # with open(MODEL_PATH, 'rb') as model_file:
        #     loaded_model = pickle.load(model_file)
        return loaded_model

    def _load_feature_schema():
        if not os.path.exists(FEATURE_SCHEMA_PATH):
            return None
        try:
            with open(FEATURE_SCHEMA_PATH, "r") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        if isinstance(data, list):
            return [str(item) for item in data]
        if isinstance(data, dict):
            for key in ("columns", "features", "feature_names", "model_features"):
                if key in data and isinstance(data[key], list):
                    return [str(item) for item in data[key]]
        return None

    def get_model_feature_names(model):
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

    @st.cache_data(ttl=43200, show_spinner=False)
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

    def build_model_input(base_df, model):
        if base_df is None or base_df.empty:
            return None
        feature_cols = get_model_feature_names(model)
        features = base_df.rename(columns=FEATURE_NAME_MAP)
        missing_cols = [col for col in feature_cols if col not in features.columns]
        if missing_cols:
            st.error(
                "Missing required stats for prediction: "
                + ", ".join(missing_cols)
                + ". The Sports-Reference page may not include these columns."
            )
            st.write("Available columns:", sorted(features.columns))
            return None
        return features[feature_cols].copy()


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

    # Your existing imports and code here...

    # Function to display PDF within Streamlit app
    @st.cache_data(show_spinner='Loading pdf...')
    def displayPDF(file):
        # Opening file from file path
        with open(file, "rb") as f:
            base64_pdf = base64.b64encode(f.read()).decode('utf-8')

        # Embedding PDF in HTML
        pdf_display = f'<embed src="data:application/pdf;base64,{base64_pdf}" width=100% height="500" type="application/pdf">'

        # Displaying File
        st.markdown(pdf_display, unsafe_allow_html=True)

    # Add this function to display the detailed context of your paper
    def display_paper_context():
        with st.expander("Learn more about the predictive model and it's background"):

            # pdf_path = "static/files/Predicting_WNBA_Success.pdf"
            # pdf_base64 = utils.get_pdf_base64(pdf_path)

            # st.markdown(
            #     f'<p style="text-align: center;"><a href="data:application/pdf;base64,{pdf_base64}" download="Predicting_WNBA_Success.pdf" target="_blank">Download Paper</a></p>',
            #     unsafe_allow_html=True
            # )


            pdf_path = PDF_PATH

            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            st.download_button(
                label="Download Paper",
                data=pdf_bytes,
                file_name="Predicting_WNBA_Success.pdf",
                mime="application/pdf",
                key='submit_wnba_download'
            )


            # Display the PDF using the function
            file_path = PDF_PATH

            displayPDF(file_path)


    # Your existing code for page_header and other parts...
    page_header('Predicting WNBA Player Success',page_name=os.path.basename(__file__))


    stu.V_SPACE(1)

    st.subheader('Predicting WNBA Success from College Performance')
    st.write("This page provides insights into WNBA players' success, leveraging predictive modeling based on college performance.")


    @st.cache_data(ttl=42300,show_spinner=False)
    def get_team_urls(year=2023):

        user_agent = random.choice(utils.user_agents) 
        headers = {'User-Agent': user_agent} 
        season_url = SEASON_URL_TEMPLATE.format(year)
        response = requests.get(season_url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html5lib')
        url_dict = utils.get_url_dict(soup)

        return {key: BASE_URL + val for key, val in url_dict.items() if f'/women/{year}' in val and '/cbb/schools/' in val}

    @st.cache_data(ttl=42300,show_spinner=False)
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


    test= get_team_urls_safe()
    if not test:
        st.error("No team data available. Check your network connection or offline fixtures.")
        st.stop()

    if _is_offline_mode():
        reason = st.session_state.get("wnba_offline_reason")
        st.warning("Offline mode enabled. Using fixture data for predictions.")
        if reason:
            st.caption(reason)
        st.caption("Set WNBA_OFFLINE=1 to force offline mode.")
    college_list = list(test.keys())
    college_list.sort()

    search_dict = {}
    col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1])

    with col1:
        current_year = datetime.datetime.now().year
        if _is_offline_mode():
            past_20_years = _get_offline_seasons() or [current_year]
        else:
            past_20_years = list(range(current_year - 19, current_year + 1))
            past_20_years.sort(reverse=True)
        search_dict["season"] = st.selectbox(
            label="Select Season", options=past_20_years, key="wnba_season"
        )

    with col2:
        search_dict["college"] = st.selectbox(
            label="Select College", options=college_list, key="wnba_college"
        )

    with col3:
        test = get_team_urls_safe(search_dict["season"])
        search_dict["team_url"] = test[search_dict["college"]]
        player_dict = get_player_urls_safe(search_dict["team_url"], search_dict["college"])
        if not player_dict:
            st.error("No player data available for this team. Check fixtures or network.")
            st.stop()
        player_list = list(player_dict)
        player_list.sort()
        search_dict["player"] = st.selectbox(
            label="Select Player", options=player_list, key="wnba_player"
        )
        search_dict["player_url"] = player_dict[search_dict["player"]]

    search = st.button("Predict Success", type="primary")

    if "validation_df" not in st.session_state:
        st.session_state["validation_df"] = None
    if "validation_meta" not in st.session_state:
        st.session_state["validation_meta"] = None

    show_validation = st.checkbox(
        "Show model input validation",
        value=False,
        key="show_model_input_validation",
    )
    if show_validation:
        validation_df = st.session_state.get("validation_df")
        validation_meta = st.session_state.get("validation_meta") or {}
        if validation_df is None:
            st.caption("Run a prediction first to see validation details.")
        else:
            st.dataframe(validation_df, hide_index=True)
            model_features = validation_meta.get("model_features")
            used_features = validation_meta.get("used_features")
            if model_features is not None and used_features is not None:
                st.caption(
                    f"Model expects {model_features} features. "
                    f"Using {used_features} features."
                )
            st.caption(
                "Note: pg_*_pct columns are decimals (e.g., 0.55 = 55%), while "
                "adv_stl_pct/adv_trb_pct/adv_ast_pct are percent points (e.g., 2.3 = 2.3%)."
            )

    if search:
        with st.spinner("Running model..."):
            base_df = get_player_df(search_dict)
            if base_df is None or base_df.empty:
                st.stop()

            if "pg_sos" not in base_df.columns or base_df["pg_sos"].isna().all():
                sos_value = get_team_sos_safe(
                    search_dict["season"],
                    search_dict["college"],
                    search_dict.get("team_url"),
                )
                if sos_value is not None:
                    base_df["pg_sos"] = sos_value
                elif "pg_sos" not in base_df.columns:
                    base_df["pg_sos"] = pd.NA

            model = init_model()
            model_input = build_model_input(base_df, model)
            if model_input is None:
                st.stop()

            st.markdown("Features used in Prediction")
            st.dataframe(
                model_input,
                column_config={
                    "pg_2p_pct": st.column_config.NumberColumn(
                        label="2-Point Field Goal Percentage", format="%.2f %%"
                    ),
                    "adv_stl_pct": st.column_config.NumberColumn(
                        label="Steal Percentage", format="%.2f %%"
                    ),
                    "pg_fg_pct": st.column_config.NumberColumn(
                        label="Field Goal Percentage", format="%.2f %%"
                    ),
                    "pg_pts": st.column_config.NumberColumn(label="Points Per Game"),
                    "pg_sos": st.column_config.NumberColumn(label="Strength of Schedule"),
                    "adv_trb_pct": st.column_config.NumberColumn(
                        label="Total Rebound Percentage", format="%.2f %%"
                    ),
                    "adv_ast_pct": st.column_config.NumberColumn(
                        label="Assist Percentage", format="%.2f %%"
                    ),
                    "pg_tov": st.column_config.NumberColumn(label="Turnovers Per Game"),
                },
                hide_index=True,
            )

            feature_cols = list(model_input.columns)
            validation_df = pd.DataFrame(
                {"feature": feature_cols, "raw_value": model_input.iloc[0].values}
            )
            st.session_state["validation_df"] = validation_df
            st.session_state["validation_meta"] = {
                "model_features": len(get_model_feature_names(model)),
                "used_features": len(feature_cols),
            }

            predicted_values = model.predict(model_input)
            prob_values = model.predict_proba(model_input)
            pred_df = base_df[["player_name"]].copy()
            pred_df["Predicted_Value"] = predicted_values
            pred_df["Probability_Pos"]  = prob_values[:,1]
            pred_df["Probability_Neg"]  = prob_values[:,0]
            pred_df.sort_values(by=['Probability_Pos'],ascending=False,inplace=True)
            player_name = base_df["player_name"].iloc[0]
            pred_prob = '{:.1%}'.format(pred_df["Probability_Pos"].iloc[0])
            result = """
            **{player_name}** predicted probability of being successful in the WNBA (Win Shares > 0):

            **{pred_prob}**
            """.format(player_name=player_name, pred_prob=pred_prob)

            st.info(result)

    stu.V_SPACE(1)



    # Call the function to display the paper context
    display_paper_context()
