"""
This is a setup.py script generated by py2applet

Usage:
    python setup.py py2app
"""

import sys


if sys.platform == "darwin":
    from setuptools import setup

    APP = ['P2PP.py']
    DATA_FILES = ['p2pp.ui', 'p2ppconf.ui', "SendError.ui", "p3browser.ui"]
    OPTIONS = {'argv_emulation': True,
               "iconfile": "icons/icon.icns",
               #"includes": ['PyQt5._qt'],
               "includes": ['PyQt5.QtWidgets','PyQt5.QtGui', 'PyQt5.Qt', 'PyQt5', 'PyQt5.QtCore'],
               "excludes": ["tkinter"]
               }

    setup(
        app=APP,
        data_files=DATA_FILES,
        options={'py2app': OPTIONS},
        install_requires = [],
        setup_requires=['py2app']
    )

else:
    import sys
    import version
    from cx_Freeze import setup, Executable

    includefiles = ["p2pp.ui", 'p2ppconf.ui', "icons/icon.ico", "SendError.ui", "p3browser.ui"]
    excludes = ["tkinter"]
    includes = ['PyQt5.QtWidgets','PyQt5.QtGui', 'PyQt5.Qt', 'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtWebEngineWidgets']

    build_exe_options = {"packages": ["os"], 'include_files': includefiles, "excludes": excludes, "includes": includes}

    setup(name="p2pp",
          version=version.Version,
          description="P2PP - Palette 2 Post Processing tool for Prusa Slicer",
          options={"build_exe": build_exe_options},
          executables=[Executable("p2pp.py", base="Win32GUI", icon="icons/icon.ico")]
          )




