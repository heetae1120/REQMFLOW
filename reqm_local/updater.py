from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


RELEASE_API = 'https://api.github.com/repos/heetae1120/REQMFLOW/releases/latest'
PACKAGE_NAME = 'REQM_FLOW_windows.zip'
CHECKSUM_NAME = PACKAGE_NAME + '.sha256'


def version_tuple(value):
    text = str(value).strip().lower().lstrip('v')
    parts = []
    for chunk in text.split('.'):
        digits = ''.join(character for character in chunk if character.isdigit())
        parts.append(int(digits or 0))
    return tuple((parts + [0, 0, 0])[:3])


def latest_release(current_version, timeout=8):
    request = urllib.request.Request(
        RELEASE_API,
        headers={'Accept':'application/vnd.github+json','User-Agent':'REQM-FLOW-Updater'},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    version = str(payload.get('tag_name','')).lstrip('v')
    if not version or version_tuple(version) <= version_tuple(current_version):
        return None
    assets = {item.get('name'):item.get('browser_download_url') for item in payload.get('assets',[])}
    if not assets.get(PACKAGE_NAME) or not assets.get(CHECKSUM_NAME):
        return None
    return {'version':version,'package_url':assets[PACKAGE_NAME],'checksum_url':assets[CHECKSUM_NAME]}


def _download(url, target, timeout=60):
    request = urllib.request.Request(url,headers={'User-Agent':'REQM-FLOW-Updater'})
    with urllib.request.urlopen(request,timeout=timeout) as response, open(target,'wb') as output:
        shutil.copyfileobj(response,output)


def prepare_update(release):
    staging = Path(tempfile.mkdtemp(prefix='REQM-FLOW-update-'))
    package = staging/PACKAGE_NAME
    checksum = staging/CHECKSUM_NAME
    _download(release['package_url'],package)
    _download(release['checksum_url'],checksum)
    expected = checksum.read_text(encoding='utf-8-sig').strip().split()[0].lower()
    actual = hashlib.sha256(package.read_bytes()).hexdigest().lower()
    if not expected or actual != expected:
        shutil.rmtree(staging,ignore_errors=True)
        raise ValueError('업데이트 파일 검증에 실패했습니다.')
    with zipfile.ZipFile(package) as archive:
        destination = staging/'unpacked'
        destination.mkdir()
        root = destination.resolve()
        for item in archive.infolist():
            target = (destination/item.filename).resolve()
            if root not in target.parents and target != root:
                raise ValueError('안전하지 않은 업데이트 파일입니다.')
        archive.extractall(destination)
    source = destination/'REQM_FLOW'
    if not (source/'REQM_FLOW.exe').exists():
        raise ValueError('업데이트 실행파일을 찾을 수 없습니다.')
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
foreach($name in @('REQM_FLOW.exe','_internal')) {
  $old = Join-Path $Target $name
  if(Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force }
}
Copy-Item -Path (Join-Path $Source '*') -Destination $Target -Recurse -Force
Start-Process -FilePath (Join-Path $Target 'REQM_FLOW.exe') -WorkingDirectory $Target
Remove-Item -LiteralPath $PSScriptRoot -Recurse -Force
''',encoding='utf-8-sig')
    flags = getattr(subprocess,'CREATE_NO_WINDOW',0)
    subprocess.Popen([
        'powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),
        '-Source',str(source),'-Target',str(install_dir),'-ProcessId',str(process_id),
    ],creationflags=flags,close_fds=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def install_directory():
    return Path(sys.executable).resolve().parent
