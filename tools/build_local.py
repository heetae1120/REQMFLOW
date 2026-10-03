"""Use an ordinary Python with Tk, or this workspace's optional build dependencies."""
import os
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
os.chdir(root)
deps=root/'build_support'
legacy_deps=root/'.builddeps'
if deps.exists():
    sys.path.insert(0,str(deps))
    os.environ['PYTHONPATH']=str(deps)
    resources=legacy_deps/'tcltk8612'/'tcl'
    if resources.exists():
        os.environ['TCL_LIBRARY']=str(resources/'tcl8.6')
        os.environ['TK_LIBRARY']=str(resources/'tk8.6')
from PyInstaller.__main__ import run
run(['--noconfirm','REQM_local.spec'])
