<div align="center"><img alt="Ambidex Logo" src="https://github.com/user-attachments/assets/5f8fc431-92ff-41f2-b563-cb15e10fd223">
<h1>Ambidex</h1>
<b>Organized backups of save files for PC games</b><br><br>
<img alt="Ambidex Preview" src="https://github.com/user-attachments/assets/ce62c97e-d50c-4cbe-88e9-5effa4538a1a" width="600">
</div>

## What is Ambidex?
**Ambidex** is a Windows app for backing up your game save data. It's designed to be quick and intuitive, making backups easy with minimal effort.

## Features
- **Effortless save detection**: Autofill game titles and auto-locate save files via **PCGamingWiki**
- **Grid layout**: Browse imported games visually with metadata + cover art from **IGDB**
- **Custom labels**: Color code and label your backups with text notes.
- **Quick backup & restore**: Back up in bulk or individually and restore backups without risk

## [Download](https://github.com/chwair/ambidex/releases/latest)
Compatible with Windows 11 and Windows 10 (1809 or later)

## Building
Ambidex is built with Nuitka. To build from source:
1. Install [Visual Studio Build Tools](https://aka.ms/vs/17/release/vs_BuildTools.exe) (with [Clang](https://learn.microsoft.com/en-us/cpp/build/clang-support-cmake?view=msvc-170#install))
2. Install dependencies:

	```bash
	pip install -r requirements.txt
	  ```
3. Run the build script
	
	```bash
	python build.py
	```

