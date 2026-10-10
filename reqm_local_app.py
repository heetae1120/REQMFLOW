import os
import sys
import ctypes
import shutil
import tempfile
from pathlib import Path


# PyInstaller's Tcl auto-discovery can lose non-ASCII installation paths on
# Windows. Point Tk at the bundled resources before tkinter is imported.
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    runtime = Path(sys._MEIPASS)
    def short_path(value):
        text = str(value)
        size = ctypes.windll.kernel32.GetShortPathNameW(text, None, 0)
        if not size:
            return text
        buffer = ctypes.create_unicode_buffer(size)
        return buffer.value if ctypes.windll.kernel32.GetShortPathNameW(text, buffer, size) else text
    tcl_source, tk_source = runtime / '_tcl_data', runtime / '_tk_data'
    tcl_path, tk_path = short_path(tcl_source), short_path(tk_source)
    if any(ord(char) > 127 for char in tcl_path + tk_path):
        cache = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'REQM-Local' / 'tcl-runtime'
        tcl_target, tk_target = cache / '_tcl_data', cache / '_tk_data'
        if not (tcl_target / 'init.tcl').exists():
            shutil.copytree(tcl_source, tcl_target, dirs_exist_ok=True)
        if not (tk_target / 'tk.tcl').exists():
            shutil.copytree(tk_source, tk_target, dirs_exist_ok=True)
        tcl_path, tk_path = str(tcl_target), str(tk_target)
    os.environ['TCL_LIBRARY'] = tcl_path
    os.environ['TK_LIBRARY'] = tk_path

from reqm_local.desktop import main

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        os.environ['REQM_SELF_TEST'] = '1'
        try:
            from reqm_local.selftest import run
            run(sys.argv[2])
        except Exception as exc:
            import json
            import traceback
            Path(sys.argv[2]).mkdir(parents=True,exist_ok=True)
            (Path(sys.argv[2])/'self-test.json').write_text(
                json.dumps({'ok':False,'error':f'{type(exc).__name__}: {exc}', 'traceback':traceback.format_exc()},ensure_ascii=False),encoding='utf-8'
            )
            os._exit(1)
        os._exit(0)
    else:
        main()
