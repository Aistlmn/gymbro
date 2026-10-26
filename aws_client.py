"""Optional SigV4 client: upload FILE or get SESSION_ID. No video is transmitted."""
import argparse
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from uuid import UUID


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(method, route, summary=None):
    base = os.environ.get('GYMBRO_API_URL', '').rstrip('/')
    parsed = urlsplit(base)
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query
            or parsed.fragment or not parsed.hostname or parsed.port not in (None,443)):
        raise ValueError('Set GYMBRO_API_URL to the HTTPS ApiUrl stack output')
    match = re.fullmatch(r'[a-z0-9]+\.execute-api\.([a-z0-9-]+)\.amazonaws\.com(?:\.cn)?', parsed.hostname)
    if not match:
        raise ValueError('Use the execute-api hostname from the stack output (no custom domains)')
    os.environ.setdefault('AWS_EC2_METADATA_DISABLED', 'true')
    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise ValueError('No AWS credentials; configure AWS_PROFILE or environment credentials')
    body = json.dumps(summary, allow_nan=False).encode('utf-8') if summary is not None else None
    url = base + route
    signed = AWSRequest(method=method, url=url, data=body, headers={'Content-Type':'application/json'})
    SigV4Auth(credentials.get_frozen_credentials(), 'execute-api', match[1]).add_auth(signed)
    req = Request(url, data=body, headers=dict(signed.headers), method=method)
    try:
        with build_opener(NoRedirect()).open(req, timeout=5) as response:
            return json.loads(response.read(150_000))
    except HTTPError as error:
        raise RuntimeError(f'AWS API returned HTTP {error.code}; check permissions, session ID and payload') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['upload','get'])
    parser.add_argument('value', help='JSON path for upload, UUID for get')
    args = parser.parse_args()
    try:
        if args.action == 'upload':
            from aws.src.schema import validate_summary
            summary = json.loads(Path(args.value).read_text(encoding='utf-8'))
            validate_summary(summary)
            result = request('POST','/sessions',summary)
        else:
            result = request('GET','/sessions/'+str(UUID(args.value)))
        print(json.dumps(result, indent=2))
    except Exception as error:
        parser.exit(1, f'{type(error).__name__}: {error}\n')


if __name__ == '__main__':
    main()
