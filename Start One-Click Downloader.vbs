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
' If pythonw isn't installed (or not on PATH), show a friendly message instead
' of the raw Windows Script Host error dialog.
On Error Resume Next
shell.Run "pythonw """ & appDir & "\oneclick.py""", 0, False
If Err.Number <> 0 Then
    MsgBox "Couldn't start the app: Python was not found." & vbCrLf & vbCrLf & _
           "Install it from https://python.org and tick ""Add to PATH"".", _
           vbExclamation, "One-Click Downloader"
End If
