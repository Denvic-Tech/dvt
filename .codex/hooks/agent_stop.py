import subprocess
import textwrap


def show_windows_toast(title: str, message: str, app_id: str = "Python.Toast.App") -> None:
    # Экранируем одинарные кавычки для PowerShell-строк
    title_ps = title.replace("'", "''")
    message_ps = message.replace("'", "''")
    app_id_ps = app_id.replace("'", "''")

    ps_script = textwrap.dedent(f"""
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null

        $xml = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{title_ps}</text>
      <text>{message_ps}</text>
    </binding>
  </visual>
</toast>
"@

        $doc = New-Object Windows.Data.Xml.Dom.XmlDocument
        $doc.LoadXml($xml)

        $toast = [Windows.UI.Notifications.ToastNotification]::new($doc)
        $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app_id_ps}')
        $notifier.Show($toast)
    """)

    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        check=True,
        capture_output=True,
        text=True,
    )


if __name__ == "__main__":
    show_windows_toast("Готово", "Toast без pip из Python 3.13")