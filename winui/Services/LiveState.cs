using Microsoft.UI.Xaml.Media.Imaging;
using System;
using System.Text.Json;
using System.Threading.Tasks;
using Windows.Storage.Streams;

namespace divoom_hub_winui3;

internal sealed class LiveState
{
    public string BackendStatus { get; set; } = "Запуск службы…";
    public bool Ready { get; set; }
    public bool DevicesPaused { get; set; }
    public bool LoggedIn { get; set; }
    public string Music { get; set; } = "Ожидание источника музыки…";
    public string Track { get; set; } = "";
    public string Artist { get; set; } = "";
    public bool Playing { get; set; }
    public BitmapImage? Cover { get; set; }
    public (string, string)[]? Builtins { get; set; }

    public static async Task<BitmapImage?> DecodeAsync(JsonElement value)
    {
        if (value.ValueKind != JsonValueKind.String) return null;
        using var stream = new InMemoryRandomAccessStream();
        using (var writer = new DataWriter(stream))
        {
            writer.WriteBytes(Convert.FromBase64String(value.GetString()!));
            await writer.StoreAsync();
            writer.DetachStream();
        }
        stream.Seek(0);
        var bitmap = new BitmapImage();
        await bitmap.SetSourceAsync(stream);
        return bitmap;
    }
}
