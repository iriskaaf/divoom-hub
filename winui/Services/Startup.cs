using Microsoft.Win32;
using System;

namespace divoom_hub_winui3;

internal static class Startup
{
    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string Entry = "DivoomHub.WinUI";
    public static bool Enabled { get { using var key = Registry.CurrentUser.OpenSubKey(RunKey); return key?.GetValue(Entry) is string; } }

    public static void Set(bool enabled)
    {
        using var key = Registry.CurrentUser.CreateSubKey(RunKey);
        if (enabled) key.SetValue(Entry, $"\"{Environment.ProcessPath}\" --minimized");
        else key.DeleteValue(Entry, throwOnMissingValue: false);
    }
}
