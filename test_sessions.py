import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

from session_store import build_summary, save_summary, upload_saved, utc_now, finish_session
from squat import SquatTracker
from test_logic import metric
from aws.src.schema import validate_summary


def workout():
    t = SquatTracker()
    now = 0
    for m,frames in [(metric(),45),(metric(100,-.4,180,.3),30),(metric(),25)]:
        for _ in range(frames):
            now += 1/30
            t.update(m,now)
    return t


def summary():
    return build_summary(workout(),utc_now(),4,'camera',{'left'},
        {'frames':100,'pose_frames':100,'usable_frames':100,'opencv_version':'5.0.0',
         'motion_frames':{'consistent':99,'inconsistent':0,'unavailable':1}},'completed')


class SessionTests(unittest.TestCase):
    def test_actual_rep_history_and_reset(self):
        t = workout()
        self.assertEqual(t.reps,1)
        self.assertEqual(len(t.rep_results),1)
        self.assertFalse(t.rep_results[0]['depth_target_met'])
        self.assertTrue(t.rep_results[0]['heel_lift_warning'])
        t.reset()
        self.assertEqual(len(t.rep_results),1)
        s = summary()
        self.assertEqual(s['form_summary'],{'depth_target_met':0,'depth_target_missed':1,'heel_lift_warnings':1})
        validate_summary(s)

    def test_local_roundtrip(self):
        s = summary()
        with tempfile.TemporaryDirectory() as folder:
            path = save_summary(s,folder)
            self.assertEqual(json.loads(path.read_text()),s)
            self.assertFalse(list(Path(folder).glob('*.tmp')))

    def test_offline_and_failure_keep_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = save_summary(summary(),folder)
            with patch.dict(os.environ,{'GYMBRO_API_URL':''}), patch('session_store.subprocess.run') as run:
                self.assertIn('disabled',upload_saved(path))
                run.assert_not_called()
            with patch.dict(os.environ,{'GYMBRO_API_URL':'https://example.invalid'}):
                for outcome in [Mock(returncode=1),subprocess.TimeoutExpired('upload',15),OSError('failure')]:
                    with patch('session_store.subprocess.run') as run:
                        if isinstance(outcome,Exception):
                            run.side_effect = outcome
                        else:
                            run.return_value = outcome
                        self.assertIn('retained',upload_saved(path))
                        self.assertEqual(run.call_args.kwargs['timeout'],15)
                        self.assertTrue(path.exists())

    def test_disk_failure_does_not_raise_or_upload(self):
        with patch('session_store.save_summary',side_effect=OSError('disk full')), patch('session_store.upload_saved') as upload:
            finish_session(summary())
            upload.assert_not_called()

    def test_bad_summary_rejected(self):
        for key,value in [('rep_count',9),('session_id','../bad'),('duration_seconds',float('nan')),
                          ('schema_version',True),('form_summary',{}),('rep_results',[{}])]:
            s = summary()
            s[key] = value
            with self.subTest(key=key), self.assertRaises((ValueError,TypeError)):
                validate_summary(s)


@unittest.skipUnless(importlib.util.find_spec('boto3'), 'Install requirements-aws.txt for AWS tests')
class BackendTests(unittest.TestCase):
    def setUp(self):
        from aws.src import handler
        self.backend = handler
        self.db = Mock()
        self.patcher = patch.object(handler,'get_table',return_value=self.db)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.s = summary()

    def post(self, s=None):
        return self.backend.handler({'httpMethod':'POST','resource':'/sessions',
            'body':json.dumps(self.s if s is None else s)},None)

    def test_create_get_retry_and_conflict(self):
        from botocore.exceptions import ClientError
        self.assertEqual(self.post()['statusCode'],201)
        item = self.db.put_item.call_args.kwargs['Item']
        self.assertEqual(self.db.put_item.call_args.kwargs['ConditionExpression'],'attribute_not_exists(session_id)')
        self.db.get_item.return_value = {'Item':item}
        result = self.backend.handler({'httpMethod':'GET','resource':'/sessions/{session_id}',
            'pathParameters':{'session_id':self.s['session_id']}},None)
        self.assertEqual(json.loads(result['body']),self.s)
        self.db.put_item.side_effect = ClientError({'Error':{'Code':'ConditionalCheckFailedException'}},'PutItem')
        self.assertEqual(self.post()['statusCode'],200)
        changed = copy.deepcopy(self.s)
        changed['duration_seconds'] += 1
        self.assertEqual(self.post(changed)['statusCode'],409)

    def test_bad_input_and_storage_failure(self):
        self.assertEqual(self.post({})['statusCode'],400)
        self.db.put_item.assert_not_called()
        self.db.get_item.return_value = {}
        get = {'httpMethod':'GET','resource':'/sessions/{session_id}',
               'pathParameters':{'session_id':self.s['session_id']}}
        self.assertEqual(self.backend.handler(get,None)['statusCode'],404)
        get['pathParameters']['session_id'] = 'invalid'
        self.assertEqual(self.backend.handler(get,None)['statusCode'],400)
        self.db.put_item.side_effect = RuntimeError('database down')
        with self.assertLogs(level='ERROR'):
            self.assertEqual(self.post()['statusCode'],503)

    def test_base64_and_body_limits(self):
        import base64
        event = {'httpMethod':'POST','resource':'/sessions','isBase64Encoded':True,
                 'body':base64.b64encode(json.dumps(self.s).encode()).decode()}
        self.assertEqual(self.backend.handler(event,None)['statusCode'],201)
        event['body'] = '???'
        self.assertEqual(self.backend.handler(event,None)['statusCode'],400)
        event['body'] = 'x'*260000
        self.assertEqual(self.backend.handler(event,None)['statusCode'],413)

    def test_signed_client_without_network(self):
        from aws_client import request
        env = {'GYMBRO_API_URL':'https://abc123.execute-api.us-east-1.amazonaws.com/Prod',
               'AWS_ACCESS_KEY_ID':'test','AWS_SECRET_ACCESS_KEY':'test','AWS_SESSION_TOKEN':'test',
               'AWS_CONFIG_FILE':os.devnull,'AWS_SHARED_CREDENTIALS_FILE':os.devnull,
               'AWS_EC2_METADATA_DISABLED':'true'}
        with patch.dict(os.environ,env),patch('aws_client.build_opener') as opener:
            os.environ.pop('AWS_PROFILE',None)
            os.environ.pop('AWS_DEFAULT_PROFILE',None)
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"stored":true}'
            self.assertTrue(request('POST','/sessions',self.s)['stored'])
            req = opener.return_value.open.call_args.args[0]
            self.assertIn('AWS4-HMAC-SHA256',req.get_header('Authorization'))
            self.assertIn('/us-east-1/execute-api/',req.get_header('Authorization'))
            self.assertEqual(json.loads(req.data),self.s)
            self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'],5)
