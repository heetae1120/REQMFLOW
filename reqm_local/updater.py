from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

from .cloud import load_cloud_config


UPDATE_BUCKET = 'reqm-updates'
UPDATE_PREFIX = 'desktop'
MANIFEST_NAME = 'latest.json'
EXE_NAME = 'REQM_FLOW.exe'
GITHUB_LATEST_URL = 'https://api.github.com/repos/heetae1120/REQMFLOW/releases/latest'
GITHUB_MANIFEST_URL = 'https://github.com/heetae1120/REQMFLOW/releases/latest/download/latest.json'


def version_tuple(value):
    text = str(value).strip().lower().lstrip('v')
    parts = []
    for chunk in text.split('.'):
        digits = ''.join(character for character in chunk if character.isdigit())
        parts.append(int(digits or 0))
    return tuple((parts + [0, 0, 0])[:3])


def update_manifest_url(config=None):
    config=config or load_cloud_config()
    return str(config.get('update_manifest_url') or GITHUB_MANIFEST_URL).strip()


def _read_json(url, timeout):
    request = urllib.request.Request(
        url,
        headers={'Accept':'application/json','User-Agent':'REQM-FLOW-Updater'},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def latest_release(current_version, timeout=8, config=None):
    try:
        release = _read_json(GITHUB_LATEST_URL, timeout)
        version = str(release.get('tag_name','')).lstrip('v')
        if not re.fullmatch(r'\d+\.\d+\.\d+',version):
            raise ValueError('GitHub 업데이트 버전이 올바르지 않습니다.')
        if version_tuple(version) <= version_tuple(current_version):
            return None
        assets = {asset['name']:asset for asset in release.get('assets',[])}
        executable = assets.get(EXE_NAME,{})
        checksum = str(executable.get('digest') or '').removeprefix('sha256:')
        download = str(executable.get('browser_download_url') or '')
        if not re.fullmatch(r'[0-9a-f]{64}',checksum) or not download.startswith(
                'https://github.com/heetae1120/REQMFLOW/releases/download/'):
            raise ValueError('GitHub 실행파일 또는 SHA-256 정보가 없습니다.')
        return {'version':version,'exe_url':download,'sha256':checksum}
    except (OSError,ValueError,KeyError,TypeError):
        # Older deployed clients still use this mirror; retain outage fallback.
        pass
    manifest_url=update_manifest_url(config)
    payload = _read_json(manifest_url, timeout)
    version = str(payload.get('version','')).lstrip('v')
    if not version or version_tuple(version) <= version_tuple(current_version):
        return None
    filename=str(payload.get('file','')).strip().lstrip('/')
    checksum=str(payload.get('sha256','')).strip().lower()
    if not filename or '..' in filename.split('/') or '\\' in filename or not re.fullmatch(r'[0-9a-f]{64}',checksum):
        raise ValueError('GitHub 업데이트 정보가 올바르지 않습니다.')
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


def launch_replacer(source, install_dir, process_id, *, restart_test_folder=None):
    source,install_dir = Path(source).resolve(),Path(install_dir).resolve()
    script = source.parent/'apply-update.ps1'
    script.write_text(r'''param([string]$Source,[string]$Target,[int]$ProcessId,[string]$RestartTestFolder='')
$ErrorActionPreference = 'Stop'
$env:PYINSTALLER_RESET_ENVIRONMENT = '1'
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
  if($RestartTestFolder) {
    Start-Process -FilePath ${targetExe} -WorkingDirectory $Target -ArgumentList @('--self-test', ('"' + $RestartTestFolder + '"')) -WindowStyle Hidden
  } else {
    Start-Process -FilePath ${targetExe} -WorkingDirectory $Target -WindowStyle Normal
  }
} catch {
  if(Test-Path -LiteralPath ${targetExe}) { Remove-Item -LiteralPath ${targetExe} -Force }
  if(Test-Path -LiteralPath ${backupExe}) { Move-Item -LiteralPath ${backupExe} -Destination ${targetExe} -Force }
  if(Test-Path -LiteralPath ${targetExe}) { Start-Process -FilePath ${targetExe} -WorkingDirectory $Target -WindowStyle Normal }
  exit 4
}
$stagePath = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$tempPath = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
if($stagePath.StartsWith($tempPath,[StringComparison]::OrdinalIgnoreCase) -and
   (Split-Path -Leaf $stagePath).StartsWith('REQM-FLOW-update-') -and
   [IO.Path]::GetFullPath((Split-Path -Parent $Source)).TrimEnd('\') -eq $stagePath) {
  Remove-Item -LiteralPath $stagePath -Recurse -Force
}
''',encoding='utf-8-sig')
    flags = getattr(subprocess,'CREATE_NO_WINDOW',0)
    command=[
        'powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),
        '-Source',str(source),'-Target',str(install_dir),'-ProcessId',str(process_id),
    ]
    if restart_test_folder is not None:
        command.extend(['-RestartTestFolder',str(Path(restart_test_folder).resolve())])
    subprocess.Popen(command,env={**os.environ,'PYINSTALLER_RESET_ENVIRONMENT':'1'},
        creationflags=flags,close_fds=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def install_directory():
    return Path(sys.executable).resolve().parent


def cleanup_legacy_install():
    """Remove only a verified old PyInstaller onedir runtime after onefile starts."""
    if not getattr(sys,'frozen',False):
        return False
    install_dir=install_directory()
    legacy=install_dir/'_internal'
    markers=(legacy/'base_library.zip',legacy/'assets'/'branding',legacy/'reference_data')
    if not all(marker.exists() for marker in markers):
        return False
    shutil.rmtree(legacy)
    previous=install_dir/'REQM_FLOW.previous.exe'
    if previous.is_file():
        previous.unlink()
    return True
