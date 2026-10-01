Set shell = CreateObject("WScript.Shell")
project = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & project & "\launch_focusmate.ps1"""
shell.Run command, 0, False