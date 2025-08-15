# This code is designed to run within a Google Cloud Function or from the command line.
# Google Cloud Function:
#   It expects a request with a message that contains a query and optionally a limit on the number of tweets to gather.
#   Example requests:
#     {"query":"olympics","bucket":"mgmt59000_twitter_tweets","user_bucket":"mgmt59000_twitter_users","debug":10,"limit":10}
#     -- This will search for 10 twitters with the term "olympics", writing the tweets to a bucket named mgmt59000_twitter_tweets
#        and the twitter users to a bucket named mgmt59000_twitter_users.
#     {"query":["olympics","swim-dive set"],"projectId":"helical-ranger-294523","topic":"twitter_tweets","userTopic":"twitter_users","bucket":"mgmt59000_twitter_tweets",
#     "userBucket":"mgmt59000_twitter_users","debug":10,"limit":10}
#     -- This will both publish in a pub/sub and store in GCS.
#     -- The query can take an array of words or phrases.
#     {"query":["olympics","tennis"],"projectId":"helical-ranger-294523","bucket":"mgmt59000_twitter_tweets","userBucket":"mgmt59000_twitter_users","path":"delimited","debug":10,"limit":100,"delim":"|"}
#     {"query":["olympics","upset"],"projectId":"helical-ranger-294523","bucket":"mgmt59000_twitter_tweets","userBucket":"mgmt59000_twitter_users","path":"arrays","debug":10,"limit":100}
# Command Line:
#   Give a query and optionally supply a limit.
#   Example calls:
#     -query olympics "swim-dive set"  -limit 25 -bucket mgmt59000_twitter_tweets -user_bucket mgmt59000_twitter_users
#     This example will search for 25 twitters mentioning olympics and "swim-dive set" and will write the filtered tweets to mgmt59000_twitter_tweets
#     and any twitter users who wrote the tweets have metadata written to mgmt59000_twitter_users.
import argparse
import datetime
import json
import logging
import re
import time

import tweepy
from google.cloud import storage
from google.cloud.exceptions import Forbidden
from google.cloud.pubsub_v1 import PublisherClient

logging.basicConfig(
  format='%(asctime)s.%(msecs)03dZ,%(pathname)s:%(lineno)d,%(levelname)s,%(module)s,%(funcName)s: %(message)s',
  datefmt="%Y-%m-%d %H:%M:%S")
_logger=logging.getLogger(__name__)

class ExampleRequest(object):
  args=None
  
  # (args.projectId,args.query,limit=args.limit,topic=args.topic,debug=args.log)
  def __init__(self, projectId, query, limit=None, topic=None, userTopic=None, bucket=None, userBucket=None,
               pathInBuckets=None,
               delim=None,
               debug=None):
    if type(query)==str:
      if not query.startswith('"'): query='"'+query+'"'
    else:
      query=json.dumps(query)
    message={'query':query, 'limit':limit if limit is not None else '', 'projectId':projectId,
             'topic':topic if topic is not None else '',
             'bucket':bucket if bucket is not None else '',
             'userTopic':userTopic if userTopic is not None else '',
             'userBucket':userBucket if userBucket is not None else ''}
    if pathInBuckets is not None: message['path']=pathInBuckets
    if delim is not None: message['delim']=delim
    if debug is not None: message['debug']=debug
    self.args={'message':json.dumps(message)}
  
  def get_json(self, force=False):
    return json.loads(self.args['message'])

def _getMessageJSON(request):
  request_json=request.get_json(force=True)
  message=None
  if request.args is not None:
    _logger.info('request is '+str(request)+' with args '+str(request.args))
    if 'message' in request.args:
      message=request.args.get('message')
    elif 'query' in request.args:
      message=request.args
  if message is None and request_json is not None:
    _logger.debug('request_json is '+str(request_json))
    if 'message' in request_json:
      message=request_json['message']
    elif 'query' in request_json:
      message=request_json
  
  if message is None:
    print('message is empty. request='+str(request)+' request_json='+str(request_json))
    message='{"query":"The Spicy Amigos"}'
  
  if type(message)==str:
    try:
      messageJSON=json.loads(message)
    except:
      messageJSON={"query":[message]}
  else:
    messageJSON=message
  return messageJSON

class MyListener(tweepy.StreamingClient):
  """Custom StreamListener for streaming data."""
  
  # _tweetFields is a list of fields to pull out of a tweet.
  _tweetFields=["created_at", "id", "id_str", "text", "in_reply_to_status_id", "in_reply_to_status_id_str",
                "in_reply_to_user_id", "in_reply_to_user_id_str", "in_reply_to_screen_name",
                "contributors", "quoted_status_id", "quoted_status_id_str", "is_quote_status", "quote_count",
                "reply_count", "retweet_count", "favorite_count", "favorited", "retweeted", "lang", "timestamp_ms"]
  # Reference fields reference other entities, such as the user who created the tweet or the original tweet for a retweet.
  # Identify which of the referenced entity's fields to use as the cross reference ID or to extract from the entity.
  _tweetReferences={"user":"id",
                    "retweeted_status":"id",
                    "hashtags":"text",
                    "user_mentions":"id",
                    "symbols":"text",
                    "extended_tweet":"full_text"}
  # Object fields have object structures as their values. We can pull out fields from the object value using the _objectFields property.
  _objectFields={"place":["name", "full_name", "country_code", "country", "place_type"]}
  # Exact location elements are structured as:
  #   "geo": {
  #     "type": "Point",
  #     "coordinates": [
  #       23.72629,
  #       84.55317
  #     ]
  #   },
  #   "coordinates": {
  #     "type": "Point",
  #     "coordinates": [
  #       84.55317,
  #       23.72629
  #     ]
  #   }
  # "geo" is an older version and is just latitude,longitude instead of longitude,latitude.
  _coordinateFields={'coordinates':['longitude', 'latitude'], 'geo':['latitude', 'longitude']}
  # _userFields is the list of fields to pull out of a user record.
  _userFields=["id", "id_str", "name", "screen_name", "location", "description", "followers_count", "friends_count",
               "listed_count", "favourites_count", "statuses_count", "created_at", "following", "follow_request_sent",
               "notifications"]
  # _multivalueTweetFields are fields that potentially have more than one value.
  _multivalueTweetFields=["hashtags", "user_mentions", "symbols", "extended_tweet"]
  
  @classmethod
  def extractFromObject(cls, field, objectValue):
    '''
    Extract the list of inner fields in cls._objectFields for the given field.
    :param field: the field that has an object value.
    :param objectValue: the actual value found in a tweet.
    :return: the list of values for the inner fields.
    '''
    extractions=[]
    if objectValue is not None:
      extractions.extend(filter(lambda item:item is not None,
                                map(lambda objectField:
                                    (field+'_'+objectField,
                                     objectValue[objectField]) if objectField in objectValue else None,
                                    cls._objectFields.get(field, []))
                                ))
    return extractions
  
  @classmethod
  def extractExactLocation(cls, field, coordinates):
    if coordinates is not None and field in cls._coordinateFields and len(cls._coordinateFields[field])==len(
        coordinates):
      return list(zip(cls._coordinateFields[field], coordinates))
  
  @classmethod
  def extractReference(cls, outerField, element):
    '''

    :param outerField: the field name of a nested field which holds information for entities the tweet is referencing.
    :param element: either a dict representing one referenced entity or a list of referenced entities.
    :return: returns a list of 0,1, or more entities referenced within element.
    '''
    entities=[]
    if outerField in cls._tweetReferences:
      subfield=cls._tweetReferences[outerField]
      if type(element)==dict:
        if subfield in element: entities.append(element[subfield])
      elif type(element)==list:
        for subelement in element:
          entities.extend(cls.extractReference(outerField, subelement))
    return entities
  
  @classmethod
  def _cleanTweet(cls, tweet, delim=None):
    if delim is None: return tweet
    cleaned={}
    for key, value in tweet.items():
      if type(value)==list:
        cleaned[key]=delim.join(map(str, value))  # Convert arrays to delimited string.
      elif type(value)==dict:
        cleaned[key]=json.dumps(value)  # Convert objects to a JSON string.
      else:
        cleaned[key]=value
    return cleaned
  
  @classmethod
  def extractTweet(cls, tweet, query, delim=None):
    '''
    Will process a single tweet and produce one or more records of tweet data. A single tweet may reference a tweet that it is retweeting, in which case this method returns both as tweet data records.
    :param tweet: the JSON from twitter representing one tweet.
    :param query: query that the tweet is a search result for.
    :return: returns one or more records of tweet data.
    '''
    if type(tweet)==bytes: return cls.extractTweet(json.loads(tweet.decode('utf-8')),query,delim=delim)
    if 'tweet' in tweet: return cls.extractTweet(tweet['tweet'], query,delim=delim)
    if 'data' in tweet: return cls.extractTweet(tweet['data'],query,delim=delim)
    tweetRows=[]
    tweetRow={}
    for field, value in tweet.items():
      if value is not None:
        if field in cls._tweetFields:
          tweetRow[field]=value
        elif field in ['user', 'retweeted_status']:
          # These nested elements only contain one object.
          referencedEntities=cls.extractReference(field, value)
          if len(referencedEntities)>0: tweetRow[field]=referencedEntities[0]
        elif field in cls._tweetReferences:
          # Capture potentially multiple references.
          referencedEntities=cls.extractReference(field, value)
          if len(referencedEntities)>0: tweetRow[field]=referencedEntities
        elif field in cls._objectFields.keys():
          # Flatten the field that has an object value.
          itemsFromObject=cls.extractFromObject(field, value)
          if len(itemsFromObject)>0: tweetRow.update(itemsFromObject)
        elif field in cls._coordinateFields.keys():
          # Pull out the components of the coordinates and store as separate fields.
          if 'coordinates' in value:
            coordinates=cls.extractExactLocation(field, value[
              'coordinates'])  # All coordinate fields have a property named "coordinates".
            if len(coordinates)>0: tweetRow.update(coordinates)
        elif field=='entities':
          # Unnest the entities object.
          for entityType, entity in value.items():
            # Capture each referenced entity.
            referencedEntities=cls.extractReference(entityType, entity)
            if len(referencedEntities)>0: tweetRow[entityType]=referencedEntities
        
        if field=='retweeted_status':
          try:
            nestedTweets=cls.extractTweet(tweet['retweeted_status'], query, delim=delim)
            tweetRows.extend(nestedTweets)
          except:
            _logger.error('SKIPPING Cannot parse nested tweet '+str(tweet['retweeted_status']), exc_info=True,
                          stack_info=True)
    tweetRow['query']=query
    if delim is None:
      # Convert empty fields for the multivalue fields into empty arrays for BigQuery since REPEATED type fields cannot be null.
      for multivalueField in MyListener._multivalueTweetFields:
        if multivalueField not in tweetRow or tweetRow[multivalueField] is None: tweetRow[multivalueField]=[]
    tweetRow['raw']=json.dumps(tweet)
    tweetRows.append(cls._cleanTweet(tweetRow, delim=delim))
    return tweetRows
  
  @classmethod
  def _extractUser(cls, userData):
    userRow={}
    for field, value in userData.items():
      if value is not None:
        if field in cls._userFields:
          userRow[field]=value
    userRow['text']=json.dumps(userData)
    return userRow
  
  @classmethod
  def extractUsers(cls, tweet):
    userRows=[]
    if type(tweet)==dict:
      if 'tweet' in tweet: return cls.extractUser(tweet['tweet'])
      for field, value in tweet.items():
        if value is not None:
          if field=='user':
            userRows.append(cls._extractUser(value))
          elif type(value) in [dict, list]:
            userRows.extend(cls.extractUsers(value))
    elif type(tweet)==list:
      for element in tweet:
        userRows.extend(cls.extractUsers(element))
    return userRows
  
  def __init__(self, bearer_token, projectId, query, limit, topic=None, userTopic=None, bucket=None, userBucket=None,
               pathInBucket=None, delim=None, debug=None):
    '''
    :param bearer_token:
    :param projectId:
    :param query:
    :param limit:
    :param topic:
    :param userTopic:
    :param bucket:
    :param userBucket:
    :param pathInBucket:
    :param delim:
    :param debug:
    '''
    super().__init__(bearer_token,wait_on_rate_limit=True,return_type=dict)
    if debug is not None: _logger.setLevel(min(debug, _logger.level))
    
    self.query=query
    self.limit=limit
    self._topic=None
    self._userTopic=None
    
    if topic is not None:
      if projectId is None: raise Exception(
        'Must supply a project ID if you want to publish to topic "{topic}".'.format(topic=topic))
      self._topic=('projects/'+projectId+'/topics/'+topic)
      _logger.debug('Output to Pub/Sub: '+self._topic)
    
    if userTopic is not None:
      if projectId is None: raise Exception(
        'Must supply a project ID if you want to publish to topic "{topic}".'.format(topic=userTopic))
      self._userTopic=('projects/'+projectId+'/topics/'+userTopic)
      _logger.debug('Output user data to Pub/Sub: '+self._userTopic)
    
    self._publisher=None
    self._userPublisher=None
    
    self._path=pathInBucket
    self._bucketClient=None
    self._userBucketClient=None
    self._bucket=bucket
    if bucket is not None:
      _logger.debug('Output to bucket: '+self._bucket)
    self._userBucket=userBucket
    if userBucket is not None:
      _logger.debug('Output user data to bucket: '+self._userBucket)
    
    self._delim=delim
  
  def _writeToBucket(self, bucketClient, bucket, records):
    key=self._createObjectKey()
    try:
      if bucketClient is None: bucketClient=storage.Client().bucket(bucket)
      for record in records:
        recordKey=key+(('_'+str(record['id'])) if 'id' in record else '')
        bucketClient.blob(recordKey).upload_from_string(json.dumps(record))
        _logger.debug('Wrote to '+recordKey)
    except Forbidden as fe:
      try:
        _logger.error(
          'Failed to write to GCS bucket {bucket} because access to object {objectName} is forbidden. Error code={code}, response content={response}'.format(
            bucket=self._bucket,
            objectName=key,
            code=str(fe.code),
            response=fe.response.content
          ), exc_info=True, stack_info=True)
      except:
        _logger.error(
          'Failed to write to GCS bucket {bucket} because access to object {objectName} is forbidden.'.format(
            bucket=self._bucket,
            objectName=key
          ), exc_info=True, stack_info=True)
    except:
      _logger.error('Failed to write to GCS bucket {bucket}, object {objectName}.'.format(
        bucket=self._bucket,
        objectName=key
      ), exc_info=True, stack_info=True)
    return bucketClient
  
  def _createObjectKey(self):
    key=''
    if type(self.query)==str:
      key+=self.query
    else:
      key+='_'.join(self.query)
    key+='_'+str(datetime.datetime.now())+'.json'
    return ('' if self._path is None else self._path+'/')+re.sub(r'[^A-Za-z0-9_.-]', '_', key)
  
  # tweets -- a dict representing a tweet (parsed with a JSON parser)
  def parseData(self, tweets):
    numTweetsStored=0
    numTweetsPublished=0
    numUsersStored=0
    numUsersPublished=0
    withinLimit=True
    try:
      tweetRecords=self.extractTweet(tweets, self.query, delim=self._delim)
      userRecords=self.extractUsers(tweets)
      
      if self._bucket is not None:
        self._bucketClient=self._writeToBucket(self._bucketClient, self._bucket, tweetRecords)
        numTweetsStored+=len(tweetRecords)
      if self._userBucket is not None:
        self._userBucketClient=self._writeToBucket(self._userBucketClient, self._userBucket, userRecords)
        numUsersStored+=len(userRecords)
      
      if self._topic is not None:
        if self._publisher is None: self._publisher=PublisherClient()
        for record in tweetRecords:
          try:
            cleanedRecord=dict(map(lambda key_value:(
              key_value[0], key_value[1] if type(key_value[1]) in [int, float, bool, str] else str(key_value[1])),
                                   record.items()))
            self._publisher.publish(self._topic, data=json.dumps(record).encode("utf-8"), **cleanedRecord)
          except:
            self._publisher.publish(self._topic, data=json.dumps(record).encode("utf-8"), query=str(self.query))
          numTweetsPublished+=1
      
      if self._userTopic is not None:
        if self._userPublisher is None: self._userPublisher=PublisherClient()
        for record in userRecords:
          try:
            self._userPublisher.publish(self._userTopic, data=json.dumps(record).encode("utf-8"), **record)
          except:
            self._userPublisher.publish(self._userTopic, data=json.dumps(record).encode("utf-8"))
          numUsersPublished+=1
      
      self.limit-=1
      if self.limit<=0: withinLimit=False
    except:
      _logger.error('Error in on_data. Sleeping for 5 seconds.', exc_info=True, stack_info=True)
      time.sleep(5)
    return (withinLimit, numTweetsStored, numUsersStored, numTweetsPublished, numUsersPublished)
  
  def on_tweet(self, data):
    print('on_data Found tweet')
    _logger.debug('Found tweet for '+str(self.query))
    withinLimit=True
    try:
      tweets=json.loads(data) if type(data)==str else data
      withinLimit, numTweetsStored, numUsersStored, numTweetsPublished, numUsersPublished=self.parseData(tweets)
    except:
      _logger.error('Error in on_data. Sleeping for 5 seconds.', exc_info=True, stack_info=True)
      time.sleep(5)
    return withinLimit
  
  def on_error(self, status):
    if status==420:
      _logger.warning('Exceeding rate limit. Exiting stream.')
      return False
    _logger.error('Received error when querying for {query}: {code}. Sleeping for 10 seconds.'.format(query=self.query,
                                                                                                      code=status),
                  exc_info=True, stack_info=True)
    time.sleep(10)
    return True

def parseTweets(request):
  """Responds to any HTTP request.
  Args:
      request (flask.Request): HTTP request object.
  Returns:
      The response text or any set of values that can be turned into a
      Response object using
      `make_response <http://flask.pocoo.org/docs/1.0/api/#flask.Flask.make_response>`.
  """
  messageJSON=_getMessageJSON(request)
  
  debug=messageJSON.get('debug', None)
  if debug is not None: _logger.setLevel(debug)
  
  _logger.info('Trigger message received is '+json.dumps(messageJSON))
  
  limit=messageJSON.get('limit', None)
  if limit is None or str(limit)=='': limit=10
  
  rawQuery=messageJSON.get('query', ['The Fast Dog'])
  if type(rawQuery)==str:
    try:
      query=json.loads(rawQuery)
    except:
      query=rawQuery
  else:
    query=rawQuery
  _logger.info('Query is "{query}", limit is set to {limit}.'.format(query=query,
                                                                     limit=str(limit) if limit is not None else 'max'))
  
  pathInBuckets=messageJSON.get('path', None)
  
  bucket=messageJSON.get('bucket', None)
  if bucket=='': bucket=None
  if bucket is not None:
    _logger.info('Using gs://{bucket}{pathInBucket} for storing tweets.'.format(bucket=bucket,
                                                                                pathInBucket='' if pathInBuckets is None else '/'+pathInBuckets))
  userBucket=messageJSON.get('userBucket', None)
  if userBucket=='': userBucket=None
  if userBucket is not None:
    _logger.info('Using gs://{bucket}{pathInBucket} for storing users.'.format(bucket=userBucket,
                                                                               pathInBucket='' if pathInBuckets is None else '/'+pathInBuckets))
  
  projectId=messageJSON.get('projectId', '')
  if projectId=='': projectId=None
  
  topic=messageJSON.get('topic', '')
  if topic=='': topic=None
  if topic is not None:
    if projectId is None:
      _logger.error('Must include a project ID if you include a topic.')
      return 'Error attempting to access Pub/Sub topic with no project ID.'
    _logger.info('Will submit tweets to {topic}.'.format(topic=topic))
  userTopic=messageJSON.get('userTopic', '')
  if userTopic=='': userTopic=None
  if userTopic is not None:
    if projectId is None:
      _logger.error('Must include a project ID if you include a topic.')
      return 'Error attempting to access Pub/Sub topic with no project ID.'
    _logger.info('Will submit users to {topic}.'.format(topic=userTopic))
  
  delim=messageJSON.get('delim', None)
  if delim is not None: _logger.info(
    'Will output multivalue fields as strings delimited by "{delim}".'.format(delim=delim))
  
  if type(query)==str: query=[query]
  
  # Set up Twitter authorization.
  # Read key and secret from file.
  with open('resources/twitterKeys.json') as twitterKeyFile:
    keys=json.load(twitterKeyFile)
  
  requiredKeys=['api_key','api_secret','bearer_token']
  if any(filter(lambda key:key not in keys, requiredKeys)):
    _logger.error(
      'Cannot read required keys from twitterKeys.json. This file must exist and have the format {"consumer_key":"...","consumer_secret":"...","access_token":"...","access_secret":"..."}.')
    return 'Cannot read required keys from twitterKeys.json'
  twitterQuery=' OR '.join(map(lambda term:'"'+term+'"',query))
  listener=MyListener(keys['bearer_token'],projectId,twitterQuery,limit,topic=topic,userTopic=userTopic,bucket=bucket,userBucket=userBucket,pathInBucket=pathInBuckets,delim=None,debug=10)
  response=listener.filter(track=','.join(query),languages='en')
  #stats=list(map(lambda tweet:listener.parseData(tweet._json),tweepy.Cursor(tweepyAPI.search,q=query).items(limit)))
  
  #nextToken=None
  #results=tweepyClient.search_recent_tweets(,next_token=nextToken)
  
  _logger.debug('Querying for {term}'.format(term=','.join(query)))
  stats=(0,0,0,0,0)
  totalTweetsStored=0
  totalUsersStored=0
  totalTweetsPublished=0
  totalUsersPublished=0
  for withinLimit, numTweetsStored, numUsersStored, numTweetsPublished, numUsersPublished in stats:
    totalTweetsStored+=numTweetsStored
    totalUsersStored+=numUsersStored
    totalTweetsPublished+=numTweetsPublished
    totalUsersPublished+=numUsersPublished
  #  twitter_stream = Stream(twitterAuth, MyListener(projectId, query, limit, topic=topic, userTopic=userTopic, bucket=bucket,
  #                                           userBucket=userBucket,pathInBucket=pathInBuckets,delim=delim,debug=debug))
  #  twitter_stream.filter(track=query)
  statsOutput='tweets stored='+str(totalTweetsStored)+',published='+str(totalTweetsPublished)+' users stored='+str(
    totalUsersStored)+',published='+str(totalUsersPublished)
  _logger.info(statsOutput)
  response=json.dumps(messageJSON)+' completed. '+statsOutput
  return response

if __name__=='__main__':
  # To call from the command line, provide two arguments: query, limit.
  parser=argparse.ArgumentParser()
  
  # add arguments to the parser
  parser.add_argument('-query', nargs='+', help='One or more terms to search form (enclose phrases in double quotes.)')
  parser.add_argument('-limit', nargs='?', help='Limit the number of calls to twitter per query term, default is 10.',
                      default=None, type=int)
  parser.add_argument('-bucket',
                      help='Provide a bucket name to store the twitter data to if you want to persist the data in GCS. The bucket must already exist.',
                      default=None)
  parser.add_argument('-userBucket',
                      help='Provide a bucket name to store the user data to if you want to persist the data in GCS. The bucket must already exist.',
                      default=None)
  parser.add_argument('-projectId',
                      help='Specify the Google cloud project ID (required when publishing to pub/sub.).',
                      default=None)
  parser.add_argument('-topic',
                      help='Specify a pub/sub topic to publish to if you want the twitter records to go to pub/sub.',
                      default=None)
  parser.add_argument('-userTopic',
                      help='Specify a pub/sub topic to publish to if you want the user records to go to pub/sub.',
                      default=None)
  parser.add_argument('-delim',
                      help='Specify a delimiter to use for multivalue fields. This causes multivalue fields to be string type instead of arrays.',
                      default=None)
  parser.add_argument('-path',
                      help='Place all tweets and users within the given path (in the tweet and user buckets).',
                      default=None)
  parser.add_argument('-debug', help='Print out log statements.', default=None, type=int)
  
  # parse the arguments
  args=parser.parse_args()
  
  exampleRequest=ExampleRequest(args.projectId, args.query, limit=args.limit, topic=args.topic,
                                userTopic=args.userTopic, bucket=args.bucket, userBucket=args.userBucket,
                                pathInBuckets=args.path,
                                delim=args.delim,
                                debug=args.debug)
  parseTweets(exampleRequest)
