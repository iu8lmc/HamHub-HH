"""Costruisce HH con PyInstaller sul sistema in uso:  python build.py
Prima:  pip install -r requirements-build.txt
Risultato: dist/HH.exe (Windows), dist/HH (Linux), dist/HH.app (macOS)."""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
if sys.platform == 'darwin':  # PyInstaller vuole un'icona .icns: la ricava da hh.ico
    from PIL import Image
    Image.open(root / 'hh.ico').convert('RGBA').resize((512, 512)).save(root / 'hh.icns')
subprocess.check_call([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', 'HH.spec'], cwd=root)
print('fatto: vedi la cartella dist/')
