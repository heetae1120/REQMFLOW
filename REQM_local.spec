# Build: pyinstaller --noconfirm REQM_local.spec
from pathlib import Path
import sys

# The repository also contains a top-level ``supabase`` data directory. Put the
# installed dependencies first so PyInstaller resolves the Supabase Python SDK
# instead of treating that data directory as a namespace package.
sys.path.insert(0, str(Path('.builddeps').resolve()))

datas=[('supabase/ecount_migration/data','reference_data'),('assets/fonts','assets/fonts'),('assets/branding','assets/branding')]
if Path('config.json').exists():
    datas.append(('config.json','.'))
a = Analysis(['reqm_local_app.py'], pathex=[],
    datas=datas,
    hiddenimports=['xlrd','msoffcrypto','olefile','cryptography','tkinterdnd2','pystray._win32','supabase','selenium','reqm_local.updater'], binaries=[], excludes=['PySide6','numpy','pandas','matplotlib','scipy','IPython','pytest'])
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='REQM_FLOW',console=False,icon='assets/branding/rq_app.ico')
coll = COLLECT(exe,a.binaries,a.datas,name='REQM_FLOW')
