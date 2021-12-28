# Slack Image Bot
This is a python script for a slack bot for posting a set of images to a Slack channel.

## Setup
### Environment Variables
- `API_URL` The URL of the image retrieval API endpoint
- `AUTHORIZED_USERS` JSON Array of Slack User IDs that are authorized to execute the commands
- `DATABASE_TABLE` The name of the AWS Dynamo DB table storing the cache
- `SLACK_BOT_TOKEN` The OAuth token for the Bot user of the Slack App
- `SLACK_IMAGE_BOT_CONTENT_CHANNEL` The ChannelID of the Slack channel the content is posted in
- `SLACK_IMAGE_BOT_ADMIN_CHANNEL` The ChannelID of the Slack channel admin messages are posted in                                                              

### Slack Bot Permissions
- `files:write`
- `chat:write`
- `commands`

### Slack Setup
The bot must be invited to the channel with `/invite [SlackApp]` so that it has permission to post in the channel.

### AWS Setup
To use the script the host must be configured to access AWS either implicitly by running in an AWS Lambda instance or explicitly using the aws CLI (see [Boto3 Docs](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/quickstart.html#configuration))

## Usage
### Slack Commands
- `/get-month [MONTH] [YEAR]` where `MONTH` is an optional number of the month (1-12). If no month is given the current month is used.
- `/get-week [WEEK] [YEAR]` where `WEEK` is an optional number of the week. If no week is given the current week is used.
### CLI Execution
The script can also be executed from the commandline. The first parameter 
`python3 main.py SLACK_USER_ID COMMAND PARAMETERS`

## Dependencies
- A server running the image retrieval API 
- `pip3 install boto3 urllib3 slack_sdk`