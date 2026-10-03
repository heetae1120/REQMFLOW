"""Build a single-file REQM FLOW executable for use on another Windows PC."""
import os
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
os.chdir(root)
support=root/'build_support'
legacy=root/'.builddeps'
sys.path.insert(0,str(support))
os.environ['PYTHONPATH']=str(support)
resources=legacy/'tcltk8612'/'tcl'
if resources.exists():
    os.environ['TCL_LIBRARY']=str(resources/'tcl8.6')
    os.environ['TK_LIBRARY']=str(resources/'tk8.6')
from PyInstaller.__main__ import run
run(['--noconfirm','--clean','REQM_local_portable.spec'])
