import datetime
import os
import pickle
import random
import re
import time

import joblib
import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from bs4 import BeautifulSoup
from sklearn.preprocessing import LabelEncoder, MinMaxScaler, StandardScaler

from app.shared_ui import st_utils as stu
from shared import utils
from app.config import BASE_DIR, CREDS
from app.layout.header import page_header
from projects.happy_prime import HappyPrime
from shared.telemetry import page_guard



with page_guard(os.path.basename(__file__)):
    def app():
        stu.V_SPACE(1)
        st.subheader("Happy Prime Calculator")

        with st.expander('Explanation'):
            st.write("""
                Start with any positive integer. Then, sum the squares of its digits. Repeat the process using the new number as your starting point. If you eventually get to the number 1, then the original number is called a 'Happy' number.
            """)
            st.write("For example, let's take the number 13:")
            st.markdown(r'''                    
                $$1^2 + 3^2 = 10$$

                $$1^2 + 0^2 = 1$$
            ''')

        col1, col2 = st.columns([1,6])

        with col1:
            user_input = st.text_input("Enter an integer", value="", key="hp_input")

        with col2:
            st.write("")  # This will add a small vertical space
            st.write("")  # This will add a small vertical space
            submit= st.button("Submit", key="submit_happy_prime")

        if submit:
            hpObj = HappyPrime(user_input)
            st.write(hpObj.result)

    page_header('Happy Prime Calculator',page_name=os.path.basename(__file__))
    app()
