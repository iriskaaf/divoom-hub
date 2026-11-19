using System;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.UI.Xaml.Media.Imaging;

namespace divoom_hub_winui3;

internal sealed class DeviceEntry
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public string Kind { get; set; } = "gate";
    public string Name { get; set; } = "Times Gate";
    public HubProfile Settings { get; set; } = new();
    [JsonIgnore] public string Address => Kind == "gate" ? Settings.TgIp : Settings.DitooAddress;
    [JsonIgnore] public ClockFace Face => Settings.TgThemes.FirstOrDefault(x => x.Id == Settings.SelectedFaceId) ?? Settings.TgThemes[0];

    public static DeviceEntry FromLegacy(string kind, HubProfile profile)
    {
        var settings = JsonSerializer.Deserialize<HubProfile>(JsonSerializer.Serialize(profile, ProfileStore.JsonWire), ProfileStore.JsonWire)!;
        settings.Devices = [];
        settings.TgToken = profile.TgToken;
        return new() { Kind = kind, Name = kind == "gate" ? "Times Gate" : "Ditoo Pro", Settings = settings };
    }
}

internal sealed class DeviceLive
{
    public bool Online { get; set; }
    public string Status { get; set; } = "Отключено";
    public BitmapImage? Frame { get; set; }
    public BitmapImage?[] Frames { get; set; } = [];
    public BitmapImage?[]? Thumbnails { get; set; }
    public string? ThumbnailKey { get; set; }
    public int Revision { get; set; }
    public long PreviewMinute { get; set; } = -1;
}
