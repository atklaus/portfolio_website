import os
from dotenv import load_dotenv

load_dotenv()

CREDS = os.environ
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
# Set this in your local environment to filter local analytics:
# export LOCAL_DEV_HOSTNAME="$(hostname)"
LOCAL_DEV = os.environ.get("LOCAL_DEV_HOSTNAME", "")

MOD_ACCESS = {
    'home': {
    'button' : ''
    ,'name' : ''
    ,'description':''
    }

    ,'wnba_success': {
    'button' : '🏀 Predicting WNBA Success'
    ,'name' : 'wnba_success'
    ,'description':"Predict WNBA success from college stats with live scraping and a cached model."
    ,'group': 'featured'
    ,'tags': ('Machine Learning', 'Classification', 'Data Pipeline', 'Web Scraping')
    }

    ,'landscape_img': {
    'button' : '🏔️  Landscape Image Prediction'
    ,'name' : 'landscape_img'
    ,'description':'Classify landscape images with a tiled CNN inference pipeline.'
    ,'group': 'featured'
    ,'tags': ('Computer Vision', 'Deep Learning', 'Model Inference', 'ML Pipeline')
    }

    ,'random_ellipses': {
    'button' : '♾️ Random Ellipses'
    ,'name' : 'ellipses'
    ,'description':'Monte Carlo overlap estimator for two ellipses.'
    ,'group': 'fun'
    ,'tags': ('Simulation', 'Monte Carlo', 'Numerical Methods')

    }

    ,'game_of_life': {
    'button' : '👾 Game of Life'
    ,'name' : 'game_of_life'
    ,'description':"Visualize Conway's Game of Life."
    ,'group': 'fun'
    ,'tags': ('Simulation', 'Algorithm Design', 'Visualization')
    }


    ,'happy_prime': {
    'button' : '🙂 Happy Prime'
    ,'name' : 'happy_prime'
    ,'description':'Determine whether a number is happy and prime.'
    ,'group': 'fun'
    ,'tags': ('Algorithms', 'Number Theory', 'Problem Solving')
    }

    ,'bibliometrix_reference_cleaner': {
    'button' : '📚 Bibliometrix Reference Cleaner'
    ,'name' : 'bibliometrix_reference_cleaner'
    ,'description':'Canonicalize Scopus/WoS references for bibliometrix/Biblioshiny.'
    ,'group': 'featured'
    ,'tags': ('Data Engineering', 'ETL', 'Fuzzy Matching', 'Record Linkage')
    }

    ,'telemetry_admin': {
    'button': '🧭 Site Analytics'
    ,'name': 'telemetry_admin'
    ,'description': 'Telemetry admin and site analytics.'
    ,'group': 'admin'
    ,'hidden': True
    ,'enabled': os.environ.get("MOD_ADMIN_ENABLED", "").strip().lower() in {"1", "true", "yes", "y"}
    }

    }
