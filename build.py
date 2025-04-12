"""
Build script
"""
import os
import subprocess

def build():
    
    cmd = [
        "python", "-m", "nuitka",
        "--standalone",
        "--windows-icon-from-ico=icon.ico",
        "--enable-plugin=pyside6",
        "--include-data-dir=images=images",
        "--windows-disable-console",
        "--assume-yes-for-downloads",
        "--show-progress",
        "--clang",
        "--output-dir=build",
        "--include-module=ui",
        "--include-module=utils",  
        "--include-module=workers",  
        "--include-package-data=PySide6",  
        "--follow-imports",  
        "ambidex.py"  
    ]
    
    subprocess.run(cmd)
    
    os.system("copy icon.ico build\\ambidex.dist\\icon.ico")
    
    if os.path.exists("config.json"):
        os.system("copy config.json build\\ambidex.dist\\config.json")

if __name__ == "__main__":
    build()