# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import boto3
import os
import json
import logging
import uuid
import time
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb_client = boto3.client("dynamodb")


def handler(event, context):
    table = os.environ.get("TABLE_NAME")
    logging.info(f"## Loaded table name from environment variable TABLE_NAME: {table}")
    
    try:
        if event["body"]:
            item = json.loads(event["body"])
            logging.info(f"## Received payload: {item}")
            year = str(item["year"])
            title = str(item["title"])
            id = str(item["id"])
            
            # Attempt DynamoDB operation with retry logic
            return put_item_with_retry(table, {
                "year": {"N": year}, 
                "title": {"S": title}, 
                "id": {"S": id}
            })
        else:
            logging.info("## Received request without a payload")
            return put_item_with_retry(table, {
                "year": {"N": "2012"},
                "title": {"S": "The Amazing Spider-Man 2"},
                "id": {"S": str(uuid.uuid4())},
            })
            
    except Exception as e:
        logging.error(f"## Error processing request: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Internal server error"}),
        }


def put_item_with_retry(table, item, max_retries=3):
    """Put item to DynamoDB with exponential backoff retry logic"""
    for attempt in range(max_retries):
        try:
            dynamodb_client.put_item(TableName=table, Item=item)
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"message": "Successfully inserted data!"}),
            }
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            # Handle throttling errors (REL05-BP02)
            if error_code in ['ProvisionedThroughputExceededException', 'ThrottlingException']:
                if attempt < max_retries - 1:
                    # Exponential backoff: 2^attempt seconds
                    wait_time = 2 ** attempt
                    logging.warning(f"## DynamoDB throttled, retrying in {wait_time}s (attempt {attempt + 1})")
                    time.sleep(wait_time)
                    continue
                else:
                    # Return 429 Too Many Requests with Retry-After header
                    logging.error("## DynamoDB throttling - max retries exceeded")
                    return {
                        "statusCode": 429,
                        "headers": {
                            "Content-Type": "application/json",
                            "Retry-After": "60"  # Suggest retry after 60 seconds
                        },
                        "body": json.dumps({
                            "error": "Too many requests",
                            "message": "Request throttled. Please retry after 60 seconds with exponential backoff."
                        }),
                    }
            else:
                # Handle other DynamoDB errors
                logging.error(f"## DynamoDB error: {error_code}")
                return {
                    "statusCode": 500,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"error": "Database error"}),
                }
    
    # This should not be reached, but included for completeness
    return {
        "statusCode": 500,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": "Unexpected error"}),
    }