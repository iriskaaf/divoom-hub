using System;
using System.IO;

namespace divoom_hub_winui3;

internal static class Edition
{
    public static bool Test => string.Equals(Path.GetFileNameWithoutExtension(Environment.ProcessPath),
        "divoom-hub-winui3_TEST", StringComparison.OrdinalIgnoreCase);
    public static string ProfileName => Test ? "DivoomHub.WinUI_TEST" : "DivoomHub.WinUI";
}
