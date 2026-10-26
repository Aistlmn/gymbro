"""API Gateway REST proxy -> validated, idempotent DynamoDB persistence."""
import base64
import json
import logging
import os
from uuid import UUID

import boto3
from botocore.exceptions import ClientError

try:
    from .schema import MAX_BYTES, validate_summary
except ImportError:  # Lambda CodeUri is this directory
    from schema import MAX_BYTES, validate_summary

table = None


def get_table():
    global table
    if table is None:
        table = boto3.resource('dynamodb').Table(os.environ['TABLE_NAME'])
    return table


def response(status, body):
    return {'statusCode':status, 'headers':{'Content-Type':'application/json','Cache-Control':'no-store'},
            'body':json.dumps(body,allow_nan=False)}


def handler(event, context):
    try:
        method = event.get('httpMethod')
        resource = event.get('resource')
        if method == 'POST' and resource == '/sessions':
            raw = event.get('body') or ''
            if len(raw) > MAX_BYTES*2:
                return response(413, {'error':'summary too large'})
            if event.get('isBase64Encoded'):
                raw = base64.b64decode(raw,validate=True).decode('utf-8')
            if len(raw.encode('utf-8')) > MAX_BYTES:
                return response(413, {'error':'summary too large'})
            summary = validate_summary(json.loads(raw))
            # JSON string preserves numbers without DynamoDB Decimal conversion.
            canonical = json.dumps(summary,sort_keys=True,separators=(',',':'),allow_nan=False)
            key = {'session_id':summary['session_id']}
            db = get_table()
            try:
                db.put_item(Item={**key,'summary_json':canonical},
                            ConditionExpression='attribute_not_exists(session_id)')
            except ClientError as error:
                if error.response['Error']['Code'] != 'ConditionalCheckFailedException':
                    raise
                old = db.get_item(Key=key,ConsistentRead=True).get('Item',{})
                if old.get('summary_json') != canonical:
                    return response(409,{'error':'session ID already has different content'})
                return response(200,{'session_id':key['session_id'],'stored':True,'duplicate':True})
            return response(201,{'session_id':key['session_id'],'stored':True,'duplicate':False})
        if method == 'GET' and resource == '/sessions/{session_id}':
            session_id = str(UUID((event.get('pathParameters') or {}).get('session_id','')))
            item = get_table().get_item(Key={'session_id':session_id},ConsistentRead=True).get('Item')
            return response(200,json.loads(item['summary_json'])) if item else response(404,{'error':'session not found'})
        return response(405,{'error':'unsupported route'})
    except (ValueError, TypeError, KeyError, UnicodeError):
        return response(400,{'error':'invalid session request'})
    except Exception:
        logging.exception('Session storage failed')
        return response(503,{'error':'storage unavailable; retry the same session later'})
