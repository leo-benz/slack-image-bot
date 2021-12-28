import locale
from time import sleep

import urllib3
import json
import os
from datetime import datetime, date
import boto3

# CONFIG
API_URL = os.environ['API_URL']
WEBHOOK_URL = os.environ['WEBHOOK_URL']
ADMIN_WEBHOOK_URL = os.environ['ADMIN_WEBHOOK_URL']
AUTHORIZED_USERS = json.loads(os.environ['AUTHORIZED_USERS'])
DATABASE_TABLE = os.environ['DATABASE_TABLE']
########

today = date.today()
statusForceList = (400, 429)
retries = urllib3.util.retry.Retry(total=10, backoff_factor=0.2, respect_retry_after_header=True,
                                   status_forcelist=statusForceList, method_whitelist=['POST'])

# GLOBALS
NUMBER = -1
YEAR = today.year
REQUEST_TYPE = ''
RESPONSE_URL = ''
HTTP = urllib3.PoolManager(retries=retries)
CACHE = boto3.resource('dynamodb').Table(DATABASE_TABLE)
########


month = today.month
week = today.isocalendar()[1]
locale.setlocale(locale.LC_ALL, 'de_DE')


def lambda_handler(event, context):
    global RESPONSE_URL, REQUEST_TYPE, month, week, YEAR, NUMBER
    print(event)
    RESPONSE_URL = event['response_url']

    if event['user_id'] not in AUTHORIZED_USERS:
        sendPrivate("Du darfst diesen Befehl nicht Ausführen!")
        return

    if event["command"] == "/get-month":
        REQUEST_TYPE = "month"
        NUMBER = month
    elif event["command"] == "/get-week":
        REQUEST_TYPE = "week"
        NUMBER = week
    else:
        sendPrivate("Unbekannter Befehl %s!" % (event["command"]))
        return

    if "text" in event:
        params = event["text"].split(" ")
        print(params)
        if len(params) > 0:
            try:
                NUMBER = int(params[0])
            except ValueError:
                sendPrivate('Parameter "%s" muss eine Zahl sein!' % (event["text"]))
                return
        if len(params) > 1:
            try:
                YEAR = int(params[1])
            except ValueError:
                sendPrivate('Parameter "%s" muss eine Zahl sein!' % (event["text"]))
                return
    r = HTTP.request('GET',
                     API_URL + 'listImages.php',
                     fields={'type': REQUEST_TYPE, 'year': YEAR, 'number': NUMBER})
    if r.status == 200:
        data = r.data.decode('utf-8')
        file_names = json.loads(data)
    elif r.status != 200:
        sendPrivate(f"HTTP Error: {r.status}")
        if r.status == 404:
            sendPrivate("Ordner für Jahr %d %s %d nicht gefunden!" % (YEAR, REQUEST_TYPE, NUMBER))
        return

    cacheName = ""
    if REQUEST_TYPE == "month":
        cacheName = datetime.strptime("%d/%d" % (YEAR, NUMBER), "%Y/%m").strftime("%Y-%B")
    else:
        cacheName = "%d-cw%d" % (YEAR, NUMBER)

    cacheItem = CACHE.get_item(Key=dict(date=cacheName))
    if 'Item' in cacheItem:
        cacheItem = cacheItem['Item']
    else:
        cacheItem = {
            'date': cacheName,
            'cache': []
        }

    if set(file_names) == set(cacheItem['cache']):
        sendPrivate("Alle Bilder bereits gesendet!")
        return

    sendHeader(len(cacheItem['cache']) > 0)

    for fileName in file_names:
        if fileName in cacheItem['cache']:
            continue
        r = HTTP.request('GET', API_URL + 'imageMetadata.php',
                         fields={'type': REQUEST_TYPE, 'year': YEAR, 'number': NUMBER, 'filename': fileName})
        try:
            meta_data = json.loads(r.data.decode('utf-8'))
            message = meta_data["exif"]
            if meta_data["iptc"]:
                message = meta_data["iptc"]
            if sendContent(meta_data["url"], message):
                cacheItem['cache'].append(fileName)
                CACHE.put_item(Item=cacheItem)
        except json.decoder.JSONDecodeError:
            sendPrivate("Error while processing %s decoding JSON message: %s" % (fileName, r.data.decode('utf-8')))

    sendAdminMessage("Befehl fertig. Es wurden %d/%d Bilder geposted." % (len(cacheItem['cache']), len(file_names)))
    CACHE.put_item(Item=cacheItem)


def sendHeader(cacheExisting=False):
    text = ""
    if REQUEST_TYPE == "month":
        text = "*Bilder des Monats %s %d*" % (datetime.strptime(str(NUMBER), "%m").strftime("%B"), YEAR)
    else:
        text = "*Bilder der Woche %d %d*" % (NUMBER, YEAR)
    if cacheExisting:
        text += " (Ergänzung)"
    response = {
        "response_type": "in_channel",
        'text': text
    }
    r = HTTP.request('POST', WEBHOOK_URL,
                     headers={'Content-Type': 'application/json'},
                     body=json.dumps(response))


def sendContent(image: str, message: str):
    sleep(1)
    print("Send Image %s with message %s" % (image, message))
    messageComponents = message.split(" / ")
    author = "Kein Autor angegeben"
    if len(messageComponents) > 0:
        author = messageComponents[0]
    title = ""
    if len(messageComponents) > 1:
        title = "/".join(messageComponents[1:])
    if len(message) == 0:
        message = author
    response = {
         "blocks": [
            {
                "type": "divider"
            },
            {
                "type": "image",
                "image_url": image,
                "block_id": "image",
                "title": {
                    "type": "plain_text",
                    "text": " "
                },
                "alt_text": message
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "*%s* %s" % (author, title)
                    }
                ]
            }
        ]
    }
    r = HTTP.request('POST', WEBHOOK_URL,
                     headers={'Content-Type': 'application/json'},
                     body=json.dumps(response),
                     retries=retries)
    print(json.dumps(response))
    print(r.status)
    print(r.data.decode('utf-8'))
    if r.status != 200:
        sendPrivate("Error %d %s sending message %s" % (r.status, r.data.decode('utf-8'), json.dumps(response)))
    return r.status == 200


def sendAdminMessage(message):
    print("Send admin message %s" % message)
    response = {
        "response_type": "in_channel",
        'text': message
    }
    r = HTTP.request('POST', ADMIN_WEBHOOK_URL,
                     headers={'Content-Type': 'application/json'},
                     body=json.dumps(response))
    print(r.status)
    print(r.data.decode('utf-8'))


def sendPrivate(message):
    print("Send private message %s" % message)
    response = {
        "response_type": "ephemeral",
        'text': message
    }
    r = HTTP.request('POST', RESPONSE_URL,
                     headers={'Content-Type': 'application/json'},
                     body=json.dumps(response))
    print(r.status)
    print(r.data.decode('utf-8'))
