# Portfolio Story

I build data products that move from raw inputs to decisions. My focus is pragmatic data engineering: reliable ingestion, normalization, clear data contracts, and production-friendly ML inference. This portfolio is a single Streamlit shell with multiple projects that share patterns for data cleaning, feature preparation, and reproducible artifacts.

## Flagship Projects

### WNBA Elite Impact Projection
Live ingestion from sports-reference.com, feature normalization, and model inference using cached artifacts to estimate top-tier WNBA career impact. Emphasis on robust parsing, missing value handling, and fast interactive prediction.  
![WNBA Elite Impact Projection](../static/images/wnba_success/screenshot.svg)  
Architecture diagram: `projects/wnba_success/README.md`  
Offline mode: `projects/wnba_success/README.md`

### Bibliometrix Reference Cleaner
ETL pipeline that parses Scopus or Web of Science exports, normalizes references, clusters duplicates, and applies canonical mappings. Emphasis on deterministic normalization, fuzzy matching tradeoffs, and repeatable outputs with tests.  
![Bibliometrix Reference Cleaner](../static/images/bibclean/screenshot.svg)  
Architecture diagram: `projects/bibclean/README.md`

### Landscape Image Prediction
ML inference pipeline that tiles images, runs a CNN model, and aggregates predictions to classify a scene. Emphasis on preprocessing, batching, and lightweight serving patterns.  
![Landscape Image Prediction](../static/images/landscape_img/screenshot.svg)  
Architecture diagram: `projects/landscape_img/README.md`

## Architecture (Data Flow)
```text
User
  -> Streamlit UI (app.py, pages/*)
      -> Project modules (projects/*)
          -> Data ingest
              - Live HTML scrape (WNBA)
              - File upload (Scopus/WoS, images)
          -> Normalize / featurize
          -> ML inference or matching
          -> Results + downloads
      -> Optional analytics storage (DigitalOcean Spaces)
```
