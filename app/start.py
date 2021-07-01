import os
import bz2
import gzip
import shutil
import re
import pickle
import json
import falcon
import srsly
import random
import urllib
import copy
import mwparserfromhell

from time import time
from datetime import date, datetime, timedelta
from multiprocessing import Process, Queue, Manager
from xml import sax
from http import client as httpcl
from html.parser import HTMLParser

from google.cloud import bigquery, storage
from google.oauth2 import service_account


#########################################################################################
# 0. General utility functions

def save_pickle_file(obj, filename, backup=False, verbose=False):
    """
    Just a convenience wrapper to pickle.dump()
    :param obj:
    :param filename:
    :param backup:
    :param verbose:
    :return:
    """

    if backup and os.path.exists(filename) and os.path.isfile(filename):
        if verbose:
            print('Renaming backup file...', filename)
        os.rename(filename, filename + '.backup')

    if filename.endswith('.gz'):
        with gzip.open(filename, 'wb') as fp:
            if verbose:
                print('Saving data to:', filename)
            pickle.dump(obj, fp, pickle.HIGHEST_PROTOCOL)
            if verbose:
                print('...saving done!')
            return True
    else:
        with open(filename, 'wb') as fp:
            if verbose:
                print('Saving data to:', filename)
            pickle.dump(obj, fp, pickle.HIGHEST_PROTOCOL)
            if verbose:
                print('...saving done!')
            return True


def read_pickle_file(filename, verbose=False):
    """
    Just a convenience wrapper to pickle.load()
    :param filename:
    :param verbose:
    :return:
    """

    if filename.endswith('.gz'):
        with gzip.open(filename, 'rb') as fp:
            if verbose:
                print('Reading data from:', filename)
            output = pickle.load(fp)
            if verbose:
                print('...reading done!')
            return output
    else:
        with open(filename, 'rb') as fp:
            if verbose:
                print('Reading data from:', filename)
            output = pickle.load(fp)
            if verbose:
                print('...reading done!')
            return output


def download_bucket_blob(bucket_name, source_blob_name, destination_file_name, storage_client):
    """Google Storage: Downloads a blob from the bucket."""
    #bucket = storage_client.bucket(bucket_name)
    #blob = bucket.blob(source_blob_name)
    #blob.download_to_filename(destination_file_name)
    #print("Blob '{}' downloaded to '{}'.".format(source_blob_name, destination_file_name))
    return


def upload_bucket_blob(bucket_name, source_file_name, destination_blob_name, storage_client):
    """Google Storage: Uploads a file to the bucket."""
    #bucket = storage_client.bucket(bucket_name)
    #blob = bucket.blob(destination_blob_name)
    #blob.upload_from_filename(source_file_name)
    #print("File '{}' uploaded to '{}'.".format(source_file_name, destination_blob_name))
    return


#########################################################################################
# 1. Basic acp_text manipulation

# clean HTML, lifted from Django:
class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.reset()
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def handle_entityref(self, name):
        self.fed.append('&%s;' % name)

    def handle_charref(self, name):
        self.fed.append('&#%s;' % name)

    def get_data(self):
        return ' '.join(self.fed)


def _strip_once(value):
    """
    Internal tag stripping utility used by strip_tags.
    """
    s = MLStripper()
    s.feed(value)
    s.close()
    return s.get_data()


def strip_tags(value):
    """Return the given HTML with all tags stripped."""
    # Note: in typical case this loop executes _strip_once once. Loop condition
    # is redundant, but helps to reduce number of executions of _strip_once.
    value = str(value)
    while '<' in value and '>' in value:
        new_value = _strip_once(value)
        if len(new_value) >= len(value):
            # _strip_once was not able to detect more tags
            break
        value = new_value
    return value


# clean text
def process_text(acp_text):
    """Clean ACP HTML and use SpaCy."""

    # brutally substitute Amedia's junk characters
    # list of forced substitutions
    subs = [('\n', ' '),
            ('\t', ' '),
            ('\xa0', ' '),
            ('&nbsp;', ' '),
            ('--', '-'),
            ('\u2002', ' '),
            ('\u2028', ' '),
            ('\u2029', ' '),
            ('  ', ' ')]

    for target, sub in subs:
        acp_text = acp_text.replace(target, sub)

    acp_text = ' '.join(acp_text.split())
    acp_text = re.sub(' +', ' ', acp_text)

    # delete Amedia's embedded scripts
    acp_text = re.sub('<script>.*?</script>', ' ', acp_text)
    acp_text = re.sub('<amedia-embed.*?</amedia-embed>', ' ', acp_text)
    # get rid of all HTML tables completely: brutal but efficient
    acp_text = re.sub('<table.*?</table>', ' ', acp_text)

    # clean whatever HTML is left at this point
    acp_text = strip_tags(acp_text)

    # last clean-up
    acp_text = re.sub(' +', ' ', acp_text)

    # this is where we could add Spacy NLP, tokenisation, lemmas, etc
    #acp_text = nlp_obj(acp_text)

    return acp_text


# apply all the cleaning functions to article object
def process_article_text(item=None):
    """Process the main text elements in an Amedia article object.
    We could implement this in a more structured way, extracting, processing
    and saving each element separately.
    In this example, we just paste all the text into a single string.
    """

    if item:
        text = ''

        # process main elements all at the same time
        # we could do this one by one, saving output in structured objects
        # I just want all the text, clean
        for element in ('title', 'leadText', 'leadtext', 'acp_text', 'body', 'content',):
            if element in item:
                if element is 'title' and not item[element].strip().endswith(('.', ':', ';', '!', '?')):
                    text = text + item[element] + '.'
                else:
                    text = text + ' ' + item[element]

        if text:
            item['nlp_text'] = process_text(text)

    return item


#########################################################################################
# 2. Amedia Content Platform (ACP): search API config and utilities

# do we have an Amedia access code to fetch content behind paywall?
# if we don't, we will get only open acp_articles
DS_ACP_AUTH_CODE = None

# we will run the example with just two newspapers
ALL_CORPUS_PUBLICATIONS = ['www.nordlys.no', 'www.nidaros.no']

# mapping Amedia JSON output to a common corpus format
# TODO: mapping several API outputs into a single format will not be easy...
def map_acp_articles(publication, acp_articles):
    # map/format output to be like text_corpus
    # notice the returned JSON by the Amedia API is recursive
    # (same keys at different levels) and not straightforward

    output = []
    for a in acp_articles['_embedded']:
        # only interested in real acp_articles with content
        if ('body' in a) and ('title' in a) and ('id' in a['fields']):

            # first the straightforward ones
            to_save = {
                'body': a['body'],
                'title': a['title'],
                '_id': a['fields']['id'],
                'id': a['fields']['id'],
                'url': publication + a['fields']['relativeUrl']
            }

            # then the remaining ones, which could fail
            if 'leadText' in a:
                to_save['leadtext'] = a['leadText']
            else:
                to_save['leadtext'] = ''
            if 'publication' in a['fields']:
                to_save['publication'] = a['fields']['publication']
            else:
                to_save['publication'] = publication
            if 'publishedDate' in a['fields']:
                to_save['published'] = a['fields']['publishedDate']
            else:
                to_save['published'] = None
            if 'authorNames' in a:
                to_save['authorNames'] = a['authorNames']
            else:
                to_save['authorNames'] = []
            if 'tags' in a:
                to_save['tags'] = [t['urlPattern'] for t in a['tags']]
            else:
                to_save['tags'] = []

            output.append(to_save)
    return output


# searching the Amedia API
def search_from_acp_api(auth_token=None, publication=None, start_date=None, end_date=None):
    """
    Utility to fetch article information from ACP search API.
    Documentation: https://developer.api.no/acp/
    GET request:
    https://services.api.no/api/acpcomposer/v1.1/search/content?publicationDomain=www.nordlys.no&startDate=2017-12-14T00:00:00&endDate=2017-12-15T00:00:00
    :return:
    """

    # without usable parameters just return, we cannot do anything
    if (publication or start_date or end_date) is None:
        return None

    # without a token we will just get open acp_articles
    if auth_token is None:
        auth_token = ''

    # print('Fetching data from ACP Search API')
    # prepare response data container
    results = None
    output = []
    params = {}
    headers = {
        # Request headers
        # 'Content-Type': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'apikey': auth_token,
    }

    # https://services.api.no/api/acpcomposer/v1.1/search/content?publicationDomain=www.nordlys.no&startDate=2017-12-14T00:00:00&endDate=2017-12-15T00:00:00
    url_root = "services.api.no"
    endpoint = "/api/acpcomposer/v1.1/search/content?publicationDomain={}&startDate={}&endDate={}".format(
        publication, start_date, end_date
    )

    try:
        conn = httpcl.HTTPSConnection(url_root, timeout=15)
        conn.request('GET', endpoint, params, headers)
        response = conn.getresponse()
        if response.status == 200:
            # print("request fetched!")
            # HTTP gives us bytes, convert to string and load json objects
            results = json.loads(response.read().decode('utf-8'))
        else:
            # print("  Response status error: {0}".format(response.status), url_root+endpoint)
            pass
        conn.close()
    except Exception as e:
        print(e, url_root + endpoint)

    if results:
        output = map_acp_articles(publication, results)

    return output


#########################################################################################
# 3. Cloud config and utilities: left here mainly as an example, we are not using them at all

# do we have an authorised client connection to Google buckets?
# the connections at Amedia are used to save/read corpus files
# and to download packaged models that we are not going to use in this instance
# this try/except block will fail

# Storage bucket info
DS_BUCKET_NAME = 'amedia-ds-research'
DS_BUCKET_CORPUS_FOLDER = 'amedia_nlp_research'
DS_BUCKET_MODEL_FOLDER = 'amedia_nlp_models'

# local model folder
LOCAL_MODEL_FOLDER = 'data'

BQ_CLIENT = None
ST_CLIENT = None
try:
    # auth key files must be provided
    # BQ auth
    KEY_FILE_BQ = 'google_auth.json'
    PROJECT_ID_BQ = json.load(open(KEY_FILE_BQ))['project_id']
    CREDENTIALS_BQ = service_account.Credentials.from_service_account_file(KEY_FILE_BQ)

    # Storage bucket DS auth
    KEY_FILE_DS = 'google_auth.json'
    PROJECT_ID_DS = json.load(open(KEY_FILE_DS))['project_id']
    CREDENTIALS_DS = service_account.Credentials.from_service_account_file(KEY_FILE_DS)

    print('BQ/ST #########################################')
    BQ_CLIENT = bigquery.Client(project=PROJECT_ID_BQ, credentials=CREDENTIALS_BQ)
    ST_CLIENT = storage.Client(project=PROJECT_ID_DS, credentials=CREDENTIALS_DS)
    print('Downloading models ############################')
    to_download = [
        (None, None),
        #(CLOUD_MODEL_FILE_KAT20, LOCAL_MODEL_FILE_KAT20),
        #(CLOUD_MODEL_FILE_SPORT, LOCAL_MODEL_FILE_SPORT),
      ]
    for source_blob_name, destination_file_name in to_download:
        if not os.path.exists(destination_file_name) and not os.path.isfile(destination_file_name):
            download_bucket_blob(DS_BUCKET_NAME, source_blob_name, destination_file_name, ST_CLIENT)
        else:
            print(
                'Model file found in container',
                destination_file_name,
                os.path.exists(destination_file_name),
                os.path.isfile(destination_file_name)
            )
except Exception as e:
        print('BQ_CLIENT/ST_CLIENT file load failed', e)

#########################################################################################
# 4. Class definition

class CompileCorpus(object):
    def __init__(self):
        self.corpus = []
        self.time_period_hours = 3
        self.nlp = None  # normally, we would pass our NLP object/class
        self.cloud_client = ST_CLIENT
        self.cloud_bucket = DS_BUCKET_NAME
        self.cloud_bucket_folder = DS_BUCKET_CORPUS_FOLDER
        self.files_in_bucket_folder = []
        self.corpus_years = [2021]
        self.corpus_months = [5, 6]

    def on_get(self, req, resp):
        """Starts compiling demo dataset from default values."""
        try:
            self.fork_process()
        except Exception as er:
            raise falcon.HTTPError(falcon.HTTP_400, "Could not fetch data from DB. fork_data_fetching_process()", er)
        finally:
            print('Process fetching data finished. New data saved.')

    def fork_process(self, dry_run=False):
        """Start a parallel process that decides if we need new data, fetches from DB and saves to datafile."""
        print('Forking process')
        p = Process(target=self.data_manager, kwargs={'dry_run': dry_run})  # args=(), kwargs={}, daemon=True
        p.start()
        p.join()

    def data_manager(self, dry_run=False):
        """This method manages the whole data fetching and saving process.
        It generates a list of corpus periods in the years/months configured,
        and for each of these, target filenames and time-slices to be fetched.
        Then, for each time-slice in each period, we send a search request,
        fetch text and process it. The results are saved to a local file,
        which is compressed at the end of the period, and uploaded to a bucket.
        """

        now = datetime.now()

        # get a list of files already present in the bucket
        self.files_in_bucket_folder = [
            # blob.name for blob in self.cloud_client.list_blobs(self.cloud_bucket, prefix=self.cloud_bucket_folder)
        ]

        # build permutations of years/months/found
        corpus_periods = [
            {
                'year': x,
                'month': y,
                'date_str': '{!s}{:02d}'.format(x, y),
                'found': z
            } for x in self.corpus_years for y in self.corpus_months for z in [False]
        ]
        # discard corpus periods in the future
        corpus_periods = [c for c in corpus_periods if not (datetime(c['year'], c['month'], 1, 0, 0, 0) > now)]

        # build filename parts to be used...
        # are we going to have full or partial periods?
        period_full = '_full'
        period_part = '_part'
        corpus_version = '_v01'
        file_ext = ['jsonl', 'gz']
        file_prefix = 'corpus_acp_nlp_monthly_'
        templ_local_prefix = 'data_processed' + '/' + file_prefix
        templ_cloud_prefix = self.cloud_bucket_folder + '/' + file_prefix
        templ_suffix = corpus_version + '.' + file_ext[0]
        templ_suffix_gz = corpus_version + '.' + file_ext[0] + '.' + file_ext[1]

        # for each period, generate time slices in truncated iso 8601 format, interval 3 hours
        for c in [c for c in corpus_periods if not c['found']]:
            print('Processing', c)
            time_slices = []
            step = timedelta(hours=self.time_period_hours)
            start = datetime(c['year'], c['month'], 1, 0, 0, 0)
            # end must be calculated, but timedelta has not implemented months: end = start + timedelta(months=1)
            # do it manually: add 1 to month if month is not december, else add 1 to year and month is january
            if c['month'] < 12:
                end = datetime(c['year'], c['month'] + 1, 1, 0, 0, 0)
            else:
                end = datetime(c['year'] + 1, 1, 1, 0, 0, 0)
            # do not make slices in the future
            if end > now:
                end = now
            # chunks with found === False must be created, adapt name to period full vs partial
            if now > end:
                c['to_create_local'] = templ_local_prefix + c['date_str'] + period_full + templ_suffix
                c['to_create_cloud'] = templ_cloud_prefix + c['date_str'] + period_full + templ_suffix_gz
            else:
                c['to_create_local'] = templ_local_prefix + c['date_str'] + period_part + templ_suffix
                c['to_create_cloud'] = templ_cloud_prefix + c['date_str'] + period_part + templ_suffix_gz

            while start < end:
                time_slices.append(
                    {
                        't_start': start.strftime('%Y-%m-%dT%H:%M:%S'),
                        't_end': (start + step).strftime('%Y-%m-%dT%H:%M:%S')
                    }
                )
                start += step

            print('Fetching acp_text from ACP ########################')
            t0 = time()
            # reduce time slices for testing
            if len(time_slices) > 10:
                time_slices = time_slices[-10:]
            print('Reducing time slices for period to ', len(time_slices))
            for p in time_slices:
                try:
                    self.fetch_corpus(start_date=p['t_start'], end_date=p['t_end'])
                except Exception as er:
                    print("Could not fetch text_corpus from ACP. Period:", p, "Error:", er)

            try:
                print(time_slices[0]['t_start'], time_slices[-1]['t_end'], 'Art', len(self.corpus), 'Time', time() - t0, 's.')
            except Exception as ex:
                print('Art', len(self.corpus), ex)

            print('Annotating acp_articles ###########################')
            if self.corpus:
                print('Articles in text_corpus:', len(self.corpus))
                try:
                    t0 = time()
                    self.process_corpus(target_file=c['to_create_local'])
                    # local corpus file is saved, let us gzip it
                    self.compress_corpus(c['to_create_local'], c['to_create_local'] + '.gz')
                    self.save_corpus(c['to_create_local'] + '.gz', c['to_create_cloud'])
                    os.remove(c['to_create_local'] + '.gz')
                    print('Done annotating!', 'Elapsed', time() - t0, 'seconds')
                except Exception as er:
                   print("Could not annotate data.", er)
                finally:
                    print('###############################################')
                    for a in self.corpus:
                        print('###', a['url'])
                        print(a['nlp_text'])
                    print('###############################################')
                    # after successful save, empty our corpus
                    self.corpus = []
            print('###############################################')

        return

    def fetch_corpus(self, start_date=None, end_date=None):
        # fetching ACP acp_text
        t0 = time()

        fetched = []
        for pub in ALL_CORPUS_PUBLICATIONS:
            fetched += search_from_acp_api(
                publication=pub,
                start_date=start_date,
                end_date=end_date
            )
        self.corpus += fetched
        return

    def process_corpus(self, target_file=None, batch_size=1000):
        print('Starting linguistic analysis...')
        count = 0
        time0 = time()
        container = []

        if not target_file:
            return

        for line in self.corpus:
            line = self.nlp_process_line(line_item=line)
            if line:
                container.append(line)
            count += 1
            if count % batch_size == 0:
                # serialize list of processed objects to JSONL
                srsly.write_jsonl(target_file, container, append=True, append_new_line=False)
                # refresh temp container
                container = []
                print('Docs processed', count, 'elapsed', time() - time0)

        # after last iteration, serialize leftovers that did not make it to batch_size
        if container:
            # serialize list of processed objects to JSONL
            srsly.write_jsonl(target_file, container, append=True, append_new_line=False)
            print('Docs processed', count, 'elapsed', time() - time0)

        print('Saved to', target_file)

        return

    def nlp_process_line(self, line_item=None):
        if line_item:
            # preprocessing, NLP
            line_item = process_article_text(item=line_item)
            # eventual classification models and more complex extraction steps
            # after NLP processing, using vectors and info from the language models
        return line_item

    def compress_corpus(self, source_fname, destination_fname):
        with open(source_fname, 'rb') as f_in:
            with gzip.open(destination_fname, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        return

    def decompress_corpus(self, source_fname, destination_fname):
        with gzip.open(source_fname, 'rb') as f_in:
            with open(destination_fname, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        return

    def save_corpus(self, source_file_name, destination_blob_name):
        return upload_bucket_blob(self.cloud_bucket, source_file_name, destination_blob_name, self.cloud_client)

    def download_corpus(self, source_file_name, destination_blob_name):
        return download_bucket_blob(self.cloud_bucket, source_file_name, destination_blob_name, self.cloud_client)


#########################################################################################
# standalone running
if __name__ == "__main__":
    # execute only if run as a script
    print('###############################################')
    print('Running as __main__ ###########################')

    try:
        print('###############################################')
        print('Compile Amedia corpus in a separate thread ####')
        this_compilation = CompileCorpus()
        this_compilation.fork_process()
    except Exception as e:
        print('Corpus compilation failed', e)
        raise e


#########################################################################################
# alternatively, it can be run as a Restful API
#api = falcon.API()

# add endpoint for each relevant class
#api.add_route('/amedia', CompileCorpus())

