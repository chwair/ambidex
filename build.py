"""
Build script for compiling the application with Nuitka
"""
import os
import subprocess

def build():
    
    # Build command
    cmd = [
        "python", "-m", "nuitka",
        "--standalone",  # Create standalone executable
        "--windows-icon-from-ico=icon.ico",  # Use our icon
        "--enable-plugin=pyside6",  # Enable PySide6 plugin
        "--include-data-dir=images=images",  # Include images directory
        "--windows-disable-console",  # No console window
        "--assume-yes-for-downloads",  # Auto-download needed tools
        "--show-progress",  # Show compilation progress
        "--clang",  # Use Clang compiler to avoid AV false positives
        "--output-dir=build",  # Output to build directory
        "ambidex.py"  # Main script
    ]
    
    # Run the build
    subprocess.run(cmd)
    
    # Copy icon file to build directory
    os.system("copy icon.ico build\\ambidex.dist\\icon.ico")

if __name__ == "__main__":
    build()