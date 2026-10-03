# Build: python tools/build_portable.py
from pathlib import Path

datas=[
    ('supabase/ecount_migration/data','reference_data'),
    ('assets/fonts','assets/fonts'),
    ('assets/branding','assets/branding'),
]
if Path('config.json').exists():
    datas.append(('config.json','.'))

a = Analysis(
    ['reqm_local_app.py'],
    pathex=[],
    datas=datas,
    hiddenimports=['xlrd','pystray._win32','supabase'],
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
