# Build: python tools/build_portable.py
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

datas=[
    ('supabase/ecount_migration/data','reference_data'),
    ('assets/fonts','assets/fonts'),
    ('assets/branding','assets/branding'),
]
selenium_hiddenimports=collect_submodules('selenium')
datas += collect_data_files('selenium')
if Path('config.json').exists():
    datas.append(('config.json','.'))

a = Analysis(
    ['reqm_local_app.py'],
    pathex=[],
    datas=datas,
    hiddenimports=['xlrd','msoffcrypto','olefile','cryptography','tkinterdnd2','pystray._win32','supabase','reqm_local.updater',*selenium_hiddenimports],
    binaries=[],
    excludes=['PySide6','numpy','pandas','matplotlib','scipy','IPython','pytest'],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='REQM_FLOW_Portable',
    console=False,
    icon='assets/branding/rq_app.ico',
)
