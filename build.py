"""
Build script
"""
import os
import subprocess
import shutil

def build():
    
    cmd = [
        "python", "-m", "nuitka",
        "--standalone",
        "--show-progress",
        "--windows-icon-from-ico=icon.ico",
        "--enable-plugin=pyside6",
        "--include-data-dir=images=images",
        "--windows-console-mode=attach",
        "--assume-yes-for-downloads",
        "--clang",
        "--output-dir=build",
        "--include-module=ui",
        "--include-module=utils",
        "--include-module=workers",  
        "--enable-plugin=pyside6",  
        "--follow-imports",
        "--lto=yes",
        "ambidex.py"  
    ]
    
    subprocess.run(cmd)
    
    os.system("copy icon.ico build\\ambidex.dist\\icon.ico")
    
    #if os.path.exists("config.json"):
    #    os.system("copy config.json build\\ambidex.dist\\config.json")
    #else:
    #    with open("build\\ambidex.dist\\config.json", "w") as f:
    #        f.write('{"backup_dir": "", "games": {}}')

if __name__ == "__main__":
    build()