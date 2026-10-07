"""Publish one verified REQM_FLOW.exe and atomically point latest.json at it."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]


def request_json(url, *, headers=None, data=None, method=None):
    request=urllib.request.Request(url,data=data,headers=headers or {},method=method)
    try:
        with urllib.request.urlopen(request,timeout=90) as response:
            body=response.read()
    except urllib.error.HTTPError as exc:
        detail=exc.read().decode('utf-8','replace')
        raise RuntimeError(f'Supabase 요청 실패 ({exc.code}): {detail}') from exc
    return json.loads(body) if body else {}


def upload(base, bucket, object_name, content, content_type, headers):
    encoded='/'.join(urllib.parse.quote(part,safe='') for part in object_name.split('/'))
    url=f"{base}/storage/v1/object/{urllib.parse.quote(bucket,safe='')}/{encoded}"
    upload_headers={**headers,'Content-Type':content_type,'x-upsert':'true'}
    request_json(url,headers=upload_headers,data=content,method='POST')


def main():
    parser=argparse.ArgumentParser(description='Supabase에 REQM FLOW EXE 업데이트 게시')
    parser.add_argument('version',help='예: 1.9.8')
    parser.add_argument('exe',nargs='?',default=str(ROOT/'dist/REQM_FLOW/REQM_FLOW.exe'))
    args=parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+',args.version):
        raise SystemExit('버전은 1.9.8 형식으로 입력하세요.')
    executable=Path(args.exe).resolve()
    if not executable.is_file():
        raise SystemExit(f'실행파일을 찾을 수 없습니다: {executable}')
    config=json.loads((ROOT/'config.json').read_text(encoding='utf-8-sig'))
    base=str(config['supabase_url']).rstrip('/')
    api_key=str(config['supabase_publishable_key'])
    email=os.environ.get('REQM_UPDATE_EMAIL','').strip()
    password=os.environ.get('REQM_UPDATE_PASSWORD','')
    if not email or not password:
        raise SystemExit('REQM_UPDATE_EMAIL과 REQM_UPDATE_PASSWORD 환경 변수를 설정하세요.')
    auth=request_json(
        f'{base}/auth/v1/token?grant_type=password',
        headers={'apikey':api_key,'Content-Type':'application/json'},
        data=json.dumps({'email':email,'password':password}).encode('utf-8'),method='POST',
    )
    token=auth.get('access_token')
    if not token:
        raise SystemExit('Supabase 로그인 토큰을 받지 못했습니다.')
    headers={'apikey':api_key,'Authorization':f'Bearer {token}'}
    bucket=str(config.get('update_bucket','reqm-updates'))
    prefix=str(config.get('update_prefix','desktop')).strip('/')
    content=executable.read_bytes()
    digest=hashlib.sha256(content).hexdigest()
    relative_file=f'{args.version}/REQM_FLOW.exe'
    upload(base,bucket,f'{prefix}/{relative_file}',content,'application/vnd.microsoft.portable-executable',headers)
    manifest=json.dumps(
        {'version':args.version,'file':relative_file,'sha256':digest},
        ensure_ascii=False,indent=2,
    ).encode('utf-8')
    upload(base,bucket,f'{prefix}/latest.json',manifest,'application/json',headers)
    print(f'게시 완료: {args.version} / SHA-256 {digest}')


if __name__=='__main__':
    main()
