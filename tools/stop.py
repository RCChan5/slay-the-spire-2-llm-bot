"""Stop every running stsbot (only processes started as "-m stsbot"; nothing else is touched).

    python -m tools.stop
"""

import subprocess

ps = ("Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
      "Where-Object { $_.CommandLine -like '*-m stsbot*' } | "
      "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }")
out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.split()
print(f"stopped {len(out)} stsbot process(es)" if out else "no stsbot running")
