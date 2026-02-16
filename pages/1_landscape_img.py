import streamlit as st
import pandas as pd
import sys
import os
from pathlib import Path
from app.config import BASE_DIR, CREDS
from app.layout.header import page_header
import datetime
from datetime import date, datetime
from dateutil import tz
import os
from app.shared_ui import st_utils as stu
import os
import cv2
from tensorflow import keras
import numpy as np
from shared.telemetry import page_guard


with page_guard(os.path.basename(__file__)):
    ROOT_DIR = Path(__file__).resolve().parents[1]
    MODEL_DIR = ROOT_DIR / "projects" / "landscape_img" / "model"

    @st.cache_resource(ttl=43200,show_spinner='Loading Model')
    def init_model():
        return keras.models.load_model(str(MODEL_DIR))


    def image_to_tiles(img, tile_size=(150, 150), overlap=50):
        tiles = []
        stride = tile_size[0] - overlap
        for x in range(0, img.shape[1] - tile_size[1] + stride, stride):
            for y in range(0, img.shape[0] - tile_size[0] + stride, stride):
                tile = img[y:y+tile_size[0], x:x+tile_size[1]]
                if tile.shape[0] == tile_size[0] and tile.shape[1] == tile_size[1]:
                    tiles.append(tile)
        return tiles

    def predict_tiles(tiles, model):
        predictions = []
        for tile in tiles:
            prediction = model.predict(tile.reshape(-1,150,150,3))
            predictions.append(prediction)
        return np.array(predictions)

    def combine_predictions(predictions):
        return predictions.mean(axis=0)

    import numpy as np

    def combine_predictions(tile_predictions):
        # Convert list of NumPy arrays to a single NumPy array
        all_predictions = np.array(tile_predictions)

        # Take the mean along axis 0 (assuming this is the axis you want)
        mean_prediction = np.mean(all_predictions, axis=0)

        return mean_prediction


    def center_crop(img, new_width=None, new_height=None):        

        width = img.shape[1]
        height = img.shape[0]

        if new_width is None:
            new_width = min(width, height)

        if new_height is None:
            new_height = min(width, height)

        left = int(np.ceil((width - new_width) / 2))
        right = width - int(np.floor((width - new_width) / 2))

        top = int(np.ceil((height - new_height) / 2))
        bottom = height - int(np.floor((height - new_height) / 2))

        if len(img.shape) == 2:
            center_cropped_img = img[top:bottom, left:right]
        else:
            center_cropped_img = img[top:bottom, left:right, ...]

        return center_cropped_img

    # Usage in your Streamlit code

    page_header('Landscape Image Prediction',page_name=os.path.basename(__file__))

    stu.V_SPACE(1)

    st.subheader('Landscape Image Prediction')

    uploaded_file = st.file_uploader("Choose an image",key='submit_landscape')
    from concurrent.futures import ThreadPoolExecutor
    import numpy as np

    def preprocess_tile(tile):
        # Perform any required pre-processing here.
        # For example, resizing, normalization, etc.
        return tile.reshape(-1, 150, 150, 3)  # Replace with your actual preprocessing steps

    def parallel_preprocess_tiles(tiles):
        with ThreadPoolExecutor() as executor:
            preprocessed_tiles = list(executor.map(preprocess_tile, tiles))
        return preprocessed_tiles

    if uploaded_file is not None:
        class_names = ['buildings', 'forest', 'glacier', 'mountain', 'sea', 'street']
        model = init_model()

        with st.spinner('Making prediction...'):
            bytes_data = uploaded_file.getvalue()
            img = cv2.imdecode(np.frombuffer(bytes_data, np.uint8), cv2.IMREAD_UNCHANGED)

            tiles = image_to_tiles(img, overlap=10)

            # Preprocess tiles in parallel
            preprocessed_tiles = parallel_preprocess_tiles(tiles)

            # Sequentially predict for each preprocessed tile
            tile_predictions = [model.predict(tile) for tile in preprocessed_tiles]

            # Combine predictions
            combined_prediction = combine_predictions(tile_predictions)
            pred = class_names[np.argmax(combined_prediction)]
        st.info('Answer: **' + pred.upper() + '**')
        st.image(img, channels="BGR")

    # with st.expander(label='Learn More'):
    #     pass
        # if st.checkbox("Training Performance",key='expand_1'):
        #     pass
            # st.write("Hello world")
        # if st.checkbox("Fake expand2",key='expand_2'):
        #     st.markdown("1. Double click into a cell to edit")
        #     st.markdown("2. Hit enter or click away to store the change")
        #     st.markdown("3. Click submit and changes will be recorded")
        #     st.markdown("4. You can validate this update by reloading the page and seeing the values")
