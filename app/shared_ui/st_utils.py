import base64

import streamlit as st


@st.cache_data(show_spinner=False, max_entries=32)
def get_image_base64(image_path):
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()


def V_SPACE(lines):
    for _ in range(lines):
        st.write("&nbsp;")
