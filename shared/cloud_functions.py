import gzip
import io
import json
import os
import secrets
import socket
import subprocess
import time
from datetime import datetime
from io import StringIO  # python3; python2: BytesIO

import boto3
import botocore.config
import pandas as pd
import streamlit as st
import extra_streamlit_components as stx
from dotenv import load_dotenv

from app.config import LOCAL_DEV
from lib.storage.s3_compat import get_storage_config, is_configured

load_dotenv()

@st.cache_resource()
def get_manager():
    return stx.CookieManager(key='cookie')

def _get_secret_value(key, required=True, default=None):
    value = None
    try:
        if key in st.secrets:
            value = st.secrets[key]
    except Exception:
        value = None
    if value is None:
        value = os.environ.get(key, default)
    if required and not value:
        raise RuntimeError(f"Missing required secret: {key}")
    return value

class CloudFunctions:
    # Snowflake Connection Config

    def __init__(self, 
                 bucket, 
                 prefix=None, 
                 webhook_id=None,
                 ):
        """
        Helper class that controls connections to AWS and makes it easier to pull/push data and connect to
        sagemaker.
        :param bucket: S3 bucket to use as the default bucket
        :param prefix: Prefix for uploading filenames, etc
        :param webhook_id: Webhook to point to the correct AWS materials
        :param cred_key: secrets key for data source
        """

        self.bucket = bucket
        self.prefix = prefix
        self.webhook_id = webhook_id

        storage_config = get_storage_config()
        if is_configured(storage_config):
            access_key = storage_config.access_key_id
            secret_key = storage_config.secret_access_key
            region = storage_config.region or "auto"
            endpoint_url = storage_config.endpoint_url
            bucket_endpoint_url = storage_config.endpoint_url
            if not self.bucket:
                self.bucket = storage_config.bucket
        else:
            access_key = _get_secret_value("DO_SPACES_KEY")
            secret_key = _get_secret_value("DO_SPACES_SECRET")
            region = os.environ.get("DO_SPACES_REGION", "nyc3")
            endpoint_url = os.environ.get(
                "DO_SPACES_ENDPOINT", f"https://{region}.digitaloceanspaces.com"
            )
            bucket_endpoint_url = os.environ.get(
                "DO_SPACES_BUCKET_ENDPOINT", f"https://{self.bucket}.{region}.digitaloceanspaces.com"
            )

        self.client = boto3.client(
            "s3",
            config=botocore.config.Config(s3={"addressing_style": "path"}),
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

        # if '/Users/adamklaus/' in BASE_DIR: 
        #     session = boto3.Session(profile_name='prod')
        #     self.s3_resource = session.resource('s3')
        #     self.s3_client = session.client('s3')
        #     self.region = session.region_name
        # else:
        #     self.s3_resource = boto3.resource('s3')
        #     self.s3_client = boto3.client('s3')
        #     self.region = boto3.Session().region_name
        session = boto3.session.Session()

        self.s3_client = session.client(
            "s3",
            region_name=region,
            endpoint_url=bucket_endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=botocore.config.Config(s3={"addressing_style": "path"}),
        )


        self.s3_resource = session.resource(
            "s3",
            region_name=region,
            endpoint_url=bucket_endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=botocore.config.Config(s3={"addressing_style": "path"}),
        )

        # self.s3_resource = session.resource('s3')
        # self.s3_client = session.client('s3')
        self.region = session.region_name

        # # Load DB CREDS from secrets
        # if cred_key is None:
        #     cred_key = CloudFunctions.SOURCE_WAREHOUSE
        # self.CREDS = json.loads(get_secret(cred_key, 'us-east-2'))

    def session_to_json(self,session_state):
        json_data = {}
        st_dict = {k: v for k, v in session_state.items() if isinstance(v, (int, float, str, list, dict))}
        json_data['result'] = st_dict
        json_data['created_at'] = str(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S%z"))
        return json_data

    def store_session(self,prefix,page_name,test=False):
        if LOCAL_DEV:
            st.session_state['Test'] = True

        if 'session_id' not in st.session_state:
            st.session_state['session_id'] = secrets.token_urlsafe(16)
            st.session_state['first_visit'] = True
            st.session_state['page_visits'] = []

        if 'cookies' not in st.session_state:
            time.sleep(.01)
            cookie_manager = get_manager()
            cookies = cookie_manager.get_all()
            st.session_state['cookies'] = cookies

        else:
            st.session_state['first_visit'] = False

        st.session_state['page_name'] = page_name
        st.session_state['page_visits'].append(page_name)
        st.session_state['hostname'] = socket.gethostname()
        if st.session_state['first_visit'] or any('submit' in key for key in st.session_state.keys()):
            json_data = self.session_to_json(st.session_state)
            self.gzip_json_and_upload_to_s3(json_data, prefix.format(str(datetime.utcnow().strftime("%Y_%m_%d_%H_%M_%S_%z"))))
            # Reset first_visit flag after storing
            # st.session_state['first_visit'] = False

    def get_df(self, query, conn=None):
        """
        Queries the database using pandas read_sql
        :param query: str, query to hit the database with
        :return: DataFrame created by the query to the database
        """
        if conn == None:
            conn = self.conn()

        return pd.read_sql(query, conn)

    def pd_read_csv_s3(self, path, *args, **kwargs):
        """
        Creates a DataFrame out of a CSV on S3
        :param path: Path to S3 file
        :param args: args to pass to pd.read_csv
        :param kwargs: kwargs to pass to pd.read_csv
        :return: DataFrame created by reading CSV in S3
        """
        return pd.read_csv(self.get_s3_file(path), *args, **kwargs)

    def s3_bucket(self, bucket=None):
        """
        Gets a bucket instance from S3 with the provided bucket name (defaults to bucket provided
        at init)
        :param bucket: Name of bucket to find on S3
        :return: Boto S3 object, bucket instance
        """
        if bucket is None:
            bucket = self.bucket
        return self.s3_resource.Bucket(bucket)

    def upload_to_s3(self, source, target, prefix=None):
        """
        Uploads a source to S3 at target.
        It will load into the bucket initiated but if a prefix
        is provided, it will use that prefix before the target name.
        If no prefix is provided, defaults to the initiatied prefix.
        :param source: Data/File/Object to upload
        :param target: Where to upload the file into the S3 bucket
        :param prefix: the path to put before the target.
        :return: None
        """
        if prefix is None:
            prefix = self.prefix

        self.s3_bucket().Object(os.path.join(prefix, target)).upload_file(source)

    def get_s3_file(self, path):
        """
        Get file from S3 using BytesIO as the engine.
        :param path: Path to s3 file
        :return: Loaded file from S3
        """
        path = path.replace("s3://", "")
        bucket, key = path.split('/', 1)
        obj = self.s3_client.get_object(Bucket=bucket, Key=key)
        byte_io = io.BytesIO(obj['Body'].read())

        return byte_io

    def s3_copy(self, source, target):
        """
        Makes an S3 object elsewhere in S3
        :param source: Location of object to be copied
        :param target: Location of where to put copy of object
        :return: None
        """
        copy_source = {
            'Bucket': self.bucket,
            'Key': os.path.join(self.prefix, source)
        }
        obj = self.s3_bucket().Object(os.path.join(self.prefix, target))
        obj.copy(copy_source)

    def download_s3_file(self, path, local_path, ignore_errors=False, prefix=None):
        """
        Downloads S3 file to local machine.
        :param path: Location on S3
        :param local_path: Local path to put download
        :param ignore_errors: bool, whether to raise exception on error
        :param prefix: str (optional), if provided will override CF provided prefix for download.
        :return: None
        """
        if prefix is None:
            prefix = self.prefix
        try:
            s3_model='s3://{}/{}/{}'.format(self.bucket, prefix, path)
            fl = self.get_s3_file(s3_model)
            with open(local_path, 'wb') as f:
                f.write(fl.read())
        except:
            exc_class, exc, tb = sys.exc_info()
            if not ignore_errors:
              raise exc

    def csv_and_upload(self, df, filename, directory=None, upload=True, header=True, index=True):
        """
        Takes a dataframe, converts it to CSV, uploads it to S3
        :param df: dataframe to save
        :param filename: what to call the saved file in s3
        :param directory: Directory to save in on s3
        :param upload: bool, upload to S3 or not
        :param header: bool, whether to save header in S3
        :param index: bool, whether to keep index in CSV or not
        :return: None
        """
        if directory is None:
            directory = filename

        csv_file = filename + '.csv'
        df.to_csv(csv_file, header=header, index=index)

        if upload:
            self.upload_to_s3(csv_file, directory + '/' + csv_file)
    
    def sync_s3_folders(self, source, target):
        subprocess.call(['aws','s3','sync',source,target,'--profile','prod'])

    def gzip_json_and_upload_to_s3(self, json_data, prefix):
        # convert dictionary to JSON string
        json_str = json.dumps(json_data)

        # create a BytesIO object
        s = io.BytesIO()

        # gzip JSON string
        with gzip.GzipFile(fileobj=s, mode='w') as f_out:
            f_out.write(json_str.encode('utf-8'))

        # get gzip data
        gzip_data = s.getvalue()

        s3object = self.s3_resource.Object(self.bucket, prefix)

        # upload gzip data to S3
        s3object.put(Body=gzip_data, ContentEncoding='gzip', ContentType='application/json')


    def json_upload(self, json_data, prefix=None):
        """[summary]

        Args:
            json_data ([type]): [description]
        """
        if prefix is None:
            prefix = self.prefix
        s3object = self.s3_resource.Object(self.bucket, prefix)
        try:
            s3object.put(Body=(bytes(json.dumps(json_data).encode('UTF-8'))))
        except:
            s3object.put(Body=(bytes(json.dumps(json_data,indent=4, sort_keys=True, default=str).encode('UTF-8'))))

    def df_upload_csv(self, df, prefix):
        """[summary]

        Args:
            df ([type]): [description]
            prefix ([type]): [description]
        """
        csv_buffer = StringIO()
        df.to_csv(csv_buffer,index=False,header=False)
        self.s3_resource.Object(self.bucket, prefix).put(Body=csv_buffer.getvalue())
    
    def get_max_file_num_from_stage(self, stage_name, snow_conn):
        """
        """
        last_file_q = """
        SELECT TOP 1 *
        FROM REFERENCE.TASK_LOG
        WHERE job_name LIKE '%{}%'
        ORDER BY end_time DESC
        """.format(stage_name)

        df = pd.read_sql(last_file_q,snow_conn)
        filename = os.path.basename(os.path.normpath(df['LOCATION'].iloc[0]))
        max_file = int(filename.split('_')[0])
        return max_file

    def convert_to_json(self, df):
        #convert df to json
        data = {}
        data['result'] = df.to_dict('records')
        data['created_at'] = str(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S%z"))
        return data


