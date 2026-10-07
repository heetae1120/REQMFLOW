from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from .cloud import load_cloud_config


UPDATE_BUCKET = 'reqm-updates'
UPDATE_PREFIX = 'desktop'
MANIFEST_NAME = 'latest.json'
EXE_NAME = 'REQM_FLOW.exe'


def version_tuple(value):
    text = str(value).strip().lower().lstrip('v')
    parts = []
    for chunk in text.split('.'):
        digits = ''.join(character for character in chunk if character.isdigit())
        parts.append(int(digits or 0))
    return tuple((parts + [0, 0, 0])[:3])


def update_manifest_url(config=None):
    config=config or load_cloud_config()
    base=str(config.get('supabase_url','')).rstrip('/')
    bucket=str(config.get('update_bucket',UPDATE_BUCKET)).strip('/')
    prefix=str(config.get('update_prefix',UPDATE_PREFIX)).strip('/')
    if not base:
        raise RuntimeError('config.json에 Supabase URL이 필요합니다.')
    path='/'.join(filter(None,(prefix,MANIFEST_NAME)))
    return f'{base}/storage/v1/object/public/{bucket}/{path}'


def latest_release(current_version, timeout=8, config=None):
    manifest_url=update_manifest_url(config)
    request = urllib.request.Request(
        manifest_url,
        headers={'Accept':'application/json','User-Agent':'REQM-FLOW-Updater'},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    version = str(payload.get('version','')).lstrip('v')
    if not version or version_tuple(version) <= version_tuple(current_version):
        return None
    filename=str(payload.get('file','')).strip().lstrip('/')
    checksum=str(payload.get('sha256','')).strip().lower()
    if not filename or '..' in filename.split('/') or '\\' in filename or not re.fullmatch(r'[0-9a-f]{64}',checksum):
        raise ValueError('Supabase 업데이트 정보가 올바르지 않습니다.')
    exe_url=urllib.parse.urljoin(manifest_url,filename) if not filename.startswith(('http://','https://')) else filename
    return {'version':version,'exe_url':exe_url,'sha256':checksum}


def _download(url, target, timeout=60):
    request = urllib.request.Request(url,headers={'User-Agent':'REQM-FLOW-Updater'})
    with urllib.request.urlopen(request,timeout=timeout) as response, open(target,'wb') as output:
        shutil.copyfileobj(response,output)


def prepare_update(release):
    staging = Path(tempfile.mkdtemp(prefix='REQM-FLOW-update-'))
    source = staging/'REQM_FLOW'
    source.mkdir()
    executable=source/EXE_NAME
    _download(release['exe_url'],executable)
    expected = str(release['sha256']).lower()
    actual = hashlib.sha256(executable.read_bytes()).hexdigest().lower()
    if not expected or actual != expected:
        shutil.rmtree(staging,ignore_errors=True)
        raise ValueError('업데이트 파일 검증에 실패했습니다.')
    return source


def launch_replacer(source, install_dir, process_id):
    source,install_dir = Path(source).resolve(),Path(install_dir).resolve()
    script = source.parent/'apply-update.ps1'
    script.write_text(r'''param([string]$Source,[string]$Target,[int]$ProcessId)
$ErrorActionPreference = 'Stop'
for($i=0; $i -lt 120; $i++) {
  if(-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { break }
  Start-Sleep -Milliseconds 250
}
if(Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) { exit 2 }
New-Item -ItemType Directory -Force -Path $Target | Out-Null
${newExe} = Join-Path $Source 'REQM_FLOW.exe'
${targetExe} = Join-Path $Target 'REQM_FLOW.exe'
${backupExe} = Join-Path $Target 'REQM_FLOW.previous.exe'
if(-not (Test-Path -LiteralPath ${newExe})) { exit 3 }
if(Test-Path -LiteralPath ${backupExe}) { Remove-Item -LiteralPath ${backupExe} -Force }
if(Test-Path -LiteralPath ${targetExe}) { Move-Item -LiteralPath ${targetExe} -Destination ${backupExe} -Force }
try {
  Copy-Item -LiteralPath ${newExe} -Destination ${targetExe} -Force
  Start-Process -FilePath ${targetExe} -WorkingDirectory $Target
} catch {
  if(Test-Path -LiteralPath ${targetExe}) { Remove-Item -LiteralPath ${targetExe} -Force }
  if(Test-Path -LiteralPath ${backupExe}) { Move-Item -LiteralPath ${backupExe} -Destination ${targetExe} -Force }
  if(Test-Path -LiteralPath ${targetExe}) { Start-Process -FilePath ${targetExe} -WorkingDirectory $Target }
  exit 4
}
Remove-Item -LiteralPath $PSScriptRoot -Recurse -Force
''',encoding='utf-8-sig')
    flags = getattr(subprocess,'CREATE_NO_WINDOW',0)
    subprocess.Popen([
        'powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),
        '-Source',str(source),'-Target',str(install_dir),'-ProcessId',str(process_id),
    ],creationflags=flags,close_fds=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def install_directory():
    return Path(sys.executable).resolve().parent
