' Double-click this to start One-Click Downloader with NO black console window.
'
' It runs the app with pythonw.exe (the windowless Python), so you only get the
' app window itself. Closing the app window quits everything.

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

' Folder this launcher lives in, so it works no matter where you put it.
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = appDir

' windowStyle 0 = hidden console; the tkinter window still shows normally.
shell.Run "pythonw """ & appDir & "\oneclick.py""", 0, False
