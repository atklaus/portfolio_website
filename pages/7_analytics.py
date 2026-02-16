import boto3
import pandas as pd
from io import BytesIO
import json
from shared.cloud_functions import CloudFunctions as CF
from app.layout.header import page_header
from app import config as c
import gzip
import io
import streamlit as st
import secrets
import plotly.express as px
import boto3
import pandas as pd
from io import BytesIO
import json
import os
import boto3
import botocore.config
import pandas as pd
from app.shared_ui import st_utils as stu
import extra_streamlit_components as stx
import uuid
import datetime
import random
import string
import bcrypt
import time
from shared.telemetry import page_guard


with page_guard(os.path.basename(__file__)):
    # Initialize boto3 client
    page_header('Analytics',page_name=os.path.basename(__file__))
    try:
        cf = CF(bucket='portfolio-website')
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    bucket_name = 'portfolio-website'
    prefix = 'analytics/activity/'  # Update this based on your folder structure

    @st.cache_data(ttl=43200, show_spinner=False)
    def fetch_data(client, bucket_name, prefix):
        response = client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
        df = pd.DataFrame()

        if 'Contents' in response:
            for item in response['Contents']:
                file_name = item['Key']
                compressed_stream = client.get_object(Bucket=bucket_name, Key=file_name)['Body'].read()
                decompressed_stream = gzip.decompress(compressed_stream)
                json_data = json.loads(decompressed_stream.decode('utf-8'))
                temp_df = pd.DataFrame([json_data])
                df = pd.concat([df, temp_df], ignore_index=True)

        return df

    def process_dataframe(df):
        # Your existing DataFrame processing logic
        df['parsed_result'] = df['result']
        all_keys = set()
        for row in df['parsed_result']:
            all_keys.update(row.keys())
        for key in all_keys:
            df[key] = df['parsed_result'].apply(lambda x: x.get(key, None))
        df.drop(columns=['parsed_result'], inplace=True)

        submit_columns = [col for col in df.columns if col.startswith("submit")]

        def get_submit_type(row):
            for col in submit_columns:
                if row[col] == True:
                    # Remove the "SUBMIT_" prefix and return
                    return col.replace("submit_", "")
            return None


        df['submit_type'] = df.apply(get_submit_type, axis=1)
        df['submit_type'].fillna('None',inplace=True)

        df = df[df['hostname'] != c.LOCAL_DEV]

        return df

    def generate_metrics(df):
        metrics = {}

        # Calculate Total Visits
        total_visits = len(df)
        metrics['total_visits'] = total_visits

        # Calculate Unique Session IDs
        unique_sessions = len(df['session_id'].unique())
        metrics['unique_sessions'] = unique_sessions

        # Calculate Active Daily Users (ADU)
        df['visit_date'] = pd.to_datetime(df['created_at'], utc=True)
        df['visit_date'] = df['visit_date'].dt.tz_convert('America/Chicago')
        df['dau_date'] = df['visit_date'].dt.date
        metric_df = df.drop_duplicates(subset=['dau_date', 'session_id'])
        adu_value = metric_df.groupby([metric_df['dau_date']]).count().mean()['session_id'].round(2)
        metrics['adu_value'] = adu_value

        return metrics

    stu.V_SPACE(1)

    if st.button('Refresh Data'):
        st.cache_data.clear()

    # Parse the JSON strings
    # if st.button('Load Report',key='submit_analytics'):

    with st.spinner('Loading report...'):

        col1, col2, col3, col4= st.columns([2,2,2,2])

        df = fetch_data(cf.client, 'portfolio-website', 'analytics/activity/')
        df = process_dataframe(df)
        metrics = generate_metrics(df)

        df['visit_date'] = pd.to_datetime(df['created_at'],utc=True)
        df['visit_date'] = df['visit_date'].dt.tz_convert('America/Chicago')
        df['dau_date']=df['visit_date'].dt.date

        # st.write(df)

        metric_df = df.copy()
        # metric_df[metric_df['VISIT_DATE'].dt.dayofweek < 5]
        metric_df = metric_df.drop_duplicates(subset=['dau_date','session_id'])
        adu_value=metric_df.groupby([metric_df['dau_date']]).count().mean()['session_id'].round(2)

        with col1:
            st.metric(label='Total Visits',value=len(df['session_id'].unique()),help='Number of people who have visited the site')
        # # with col2:
        # #     st.metric(label='Unique Visitors',value=len(df['session_id'].unique()),help='Number of unique people to visit the site')
        with col3:
            st.metric(label='Active Daily Users',value=adu_value,help='daily average of [unique new users] + [unique returning users]')
        with col4:
            pass

        line_df = df.copy()
        line_df = line_df.drop_duplicates(subset=['session_id'])
        line_df['visit_date'] = pd.to_datetime(line_df['visit_date'],utc=True)
        line_df['visit_date'] = line_df['visit_date'].dt.tz_convert('America/Chicago')

        line_df['visit_date']=line_df['visit_date'].dt.date
        line_df = line_df.groupby([line_df['visit_date']]).count()
        # Set the index as the date column
        line_df.reset_index(inplace=True)
        # # Create the line chart
        fig = px.line(line_df, x='visit_date', y='session_id',title='Visitors Over Time')

        fig.update_layout(yaxis={'title': 'VISITS'})

        # # # Show the chart using Streamlit
        st.plotly_chart(fig, use_container_width=True)

        # Now `df` contains data from all JSON files if any were found
        st.dataframe(data=df,
                column_order=['created_at','submit_type','page_name','page_visits'],        
                column_config={"created_at": st.column_config.DatetimeColumn(format='MMM D, YYYY h:mm a',timezone='America/Chicago')},
                hide_index=True,
                use_container_width=True
                )
