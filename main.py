import json
import locale
import logging
import os
import sys
from datetime import datetime, date
from io import BytesIO
from time import sleep

import boto3
import urllib3
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# CONFIG
API_URL = os.environ['API_URL']
AUTHORIZED_USERS = json.loads(os.environ['AUTHORIZED_USERS'])
DATABASE_TABLE = os.environ['DATABASE_TABLE']
SLACK_BOT_TOKEN = os.environ['SLACK_BOT_TOKEN']
CONTENT_CHANNEL = os.environ['SLACK_IMAGE_BOT_CONTENT_CHANNEL']
ADMIN_CHANNEL = os.environ['SLACK_IMAGE_BOT_ADMIN_CHANNEL']
########

# Global Class instances
logger = logging.getLogger()
if logging.getLogger().hasHandlers():
    logging.getLogger().setLevel(logging.INFO)
else:
    logging.basicConfig(level=logging.INFO)

slack_client = WebClient(token=SLACK_BOT_TOKEN)

statusForceList = (400, 429)
retries = urllib3.util.retry.Retry(total=10, backoff_factor=0.2, respect_retry_after_header=True,
                                   status_forcelist=statusForceList)
http = urllib3.PoolManager(retries=retries)
########

# Global variables
INVOCATION_USER_ID = ''
INVOCATION_CHANNEL_ID = ''
########


def lambda_handler(event, context):
    """
    Main method for the AWS lambda instance based on the Slack Command API invocation
    :param event: The POST parameters received from Slack (see [API Docs](https://api.slack.com/interactivity/slash-commands#app_command_handling))
    :param context: The AWS lambda execution context (see [API Docs](https://docs.aws.amazon.com/lambda/latest/dg/python-context.html)
    """
    global INVOCATION_USER_ID, INVOCATION_CHANNEL_ID

    # Configuration of global objects
    logger.debug(event)
    locale.setlocale(locale.LC_ALL, 'de_DE')

    # Initialization of local variables
    number = -1
    request_type = ''
    today = date.today()
    month = today.month
    week = today.isocalendar()[1]
    year = today.year
    aws_cache = boto3.resource('dynamodb').Table(DATABASE_TABLE)

    # Store the information about the invoking user and channel as a global variable
    INVOCATION_USER_ID = event['user_id']
    INVOCATION_CHANNEL_ID = event['channel_id']

    # Check if invoking user is allowed to execute commands
    if INVOCATION_USER_ID not in AUTHORIZED_USERS:
        send_private_message("Du darfst diesen Befehl nicht Ausführen!")
        return

    # Check which command was executed
    if event["command"] == "/get-month":
        request_type = "month"
        number = month
    elif event["command"] == "/get-week":
        request_type = "week"
        number = week
    else:
        send_private_message("Unbekannter Befehl %s!" % (event["command"]))
        return

    # Process command parameters
    if "text" in event:
        params = event["text"].split(" ")
        print(params)
        if len(params) > 0:
            try:
                number = int(params[0])
            except ValueError:
                send_private_message('Parameter "%s" muss eine Zahl sein!' % (event["text"]))
                return
        if len(params) > 1:
            try:
                year = int(params[1])
            except ValueError:
                send_private_message('Parameter "%s" muss eine Zahl sein!' % (event["text"]))
                return

    # Get list of images from Image API
    r = http.request('GET',
                     API_URL + 'listImages.php',
                     fields={'type': request_type, 'year': year, 'number': number})
    if r.status == 200:
        data = r.data.decode('utf-8')
        file_names = json.loads(data)
    elif r.status != 200:
        send_private_message(f"HTTP Error when retrieving list of images: {r.status}")
        if r.status == 404:
            send_private_message("Ordner für Jahr %d %s %d nicht gefunden!" % (year, request_type, number))
        return

    # Load cache from AWS
    cache_name = ""
    if request_type == "month":
        cache_name = datetime.strptime("%d/%d" % (year, number), "%Y/%m").strftime("%Y-%B")
    else:
        cache_name = "%d-cw%d" % (year, number)

    cache_item = aws_cache.get_item(Key=dict(date=cache_name))
    if 'Item' in cache_item:
        cache_item = cache_item['Item']
    else:
        cache_item = {
            'date': cache_name,
            'cache': []
        }

    # If all items are included in cache end script execution early
    if set(file_names) == set(cache_item['cache']):
        send_private_message("Alle Bilder bereits gesendet!")
        return

    send_header_message(request_type, number, year, len(cache_item['cache']) > 0)

    # Get metadata for every file and send content messages
    for fileName in file_names:
        # Skip cached images
        if fileName in cache_item['cache']:
            continue
        # Retrieve metadata for file from image API
        r = http.request('GET', API_URL + 'imageMetadata.php',
                         fields={'type': request_type, 'year': year, 'number': number, 'filename': fileName})
        # Decode metadata
        try:
            meta_data = json.loads(r.data.decode('utf-8'))
            message = meta_data["exif"]
            if meta_data["iptc"]:
                message = meta_data["iptc"]
            # If message sent successful add it to the cache
            if send_content_message(meta_data["url"], message):
                cache_item['cache'].append(fileName)
                aws_cache.put_item(Item=cache_item)
        except json.decoder.JSONDecodeError:
            send_private_message("Error while processing %s decoding JSON message: %s" % (fileName, r.data.decode('utf-8')))

    send_admin_message("Befehl fertig. Es wurden %d/%d Bilder geposted." % (len(cache_item['cache']), len(file_names)))


def send_header_message(request_type, number, year, cache_existing=False):
    """
    Sends the introductory header message to the content channel
    :param request_type: If type is `month` alternative header text is used
    :param number: Added as information to the message. This is interpreted based on the `request_type` as week number or month
    :param year: The year to be included in the message
    :param cache_existing: If `True` header includes note that following content is a supplement to existing content
    """
    message = ""
    if request_type == "month":
        message = "*Bilder des Monats %s %d*" % (datetime.strptime(str(number), "%m").strftime("%B"), year)
    else:
        message = "*Bilder der Woche %d %d*" % (number, year)
    if cache_existing:
        message += " (Ergänzung)"

    logger.debug("Send header message %s" % message)
    try:
        slack_client.chat_postMessage(
            channel=CONTENT_CHANNEL,
            as_user=False,
            text=message
        )
    except SlackApiError as e:
        logger.error(e)


def send_content_message(image: str, message: str):
    """
    Send message with the image, author and title
    :param image: The image url
    :param message: The message
    :return: True if message sent successful
    """

    # Wait for 3 seconds to ensure adherence to Slacks file.upload Tier2 API rate limit of 20 calls per minute
    sleep(3)

    logger.debug(f"Send Image {image} with message {message}")
    message_components = message.split(" / ")
    author = "Kein Autor angegeben"
    if len(message_components) > 0:
        author = message_components[0]
    title = ""
    if len(message_components) > 1:
        title = "/".join(message_components[1:])
    if len(message) == 0:
        message = author

    try:
        img_request = http.request('GET', image)
        # TODO: Handle as exception
        if img_request.status != 200:
            send_private_message(f"Error while downloading image from {image}. Status: {img_request.status}")
            return False
        result = slack_client.files_upload(
            channels=CONTENT_CHANNEL,
            initial_comment=f"*{author}* {title}",
            file=BytesIO(img_request.data),
            filename=" "
        )
        return True
    except SlackApiError as e:
        logger.error(e)
        send_private_message(f"Error sending message: {e}")
        return False


def send_admin_message(message):
    """
    Sends the given message to the admin channel
    :param message: The message to send
    """
    logger.debug("Send admin message %s" % message)
    try:
        slack_client.chat_postMessage(
            channel=ADMIN_CHANNEL,
            as_user=False,
            text=message
        )
    except SlackApiError as e:
        logger.error(e)


def send_private_message(message):
    """
    Sends the given message as an ephemeral message privately to the user that invoked the command
    :param message: The message to send
    """
    logger.debug("Send private message %s" % message)
    try:
        slack_client.chat_postEphemeral(
            channel=INVOCATION_CHANNEL_ID,
            user=INVOCATION_USER_ID,
            as_user=False,
            text=message
        )
    except SlackApiError as e:
        logger.error(e)


def main():
    event = {
        "user_id": sys.argv[1],
        "command": sys.argv[2],
        "text": " ".join(sys.argv[3:]),
        "channel_id": ADMIN_CHANNEL
    }
    lambda_handler(event)


if __name__ == "__main__":
    main()
