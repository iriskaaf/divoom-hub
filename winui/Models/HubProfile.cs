using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace divoom_hub_winui3;

// Settings editable in the UI. Keep the draft separate from the running Python app.
internal sealed class HubProfile
{
    public int DeviceSchema { get; set; }
    public List<DeviceEntry> Devices { get; set; } = [];
    public bool OnboardingCompleted { get; set; }
    public bool DitooEnabled { get; set; }
    public bool TimesgateEnabled { get; set; }
    public string DitooAddress { get; set; } = "";
    public int DitooPort { get; set; }
    public bool AutoReconnect { get; set; } = true;
    public int Brightness { get; set; } = 60;
    public string IdleMode { get; set; } = "clock";
    public int IdleDelayS { get; set; } = 5;
    public double Contrast { get; set; } = 1.1;
    public double Saturation { get; set; } = 1.15;
    public double ArtBrightness { get; set; } = 1;
    public string TgIp { get; set; } = "";
    public string TgMac { get; set; } = "";
    [JsonIgnore] public string TgToken { get; set; } = "";
    public int TgHardware { get; set; } = 400;
    public string TgMode { get; set; } = "clock";
    public int TgDeviceFace { get; set; } = 581;
    public bool TgDeviceFaceOnExit { get; set; } = true;
    public bool Tg24h { get; set; } = true;
    public bool TgBlinkColon { get; set; } = true;
    public int TgBrightness { get; set; } = 80;
    public bool TgCenterCover { get; set; } = true;
    public bool TgFaceFollowCover { get; set; }
    public bool TgLightFollowCover { get; set; }
    public bool TgLightOn { get; set; } = true;
    public int TgLightZone { get; set; }
    public int TgLightEffect { get; set; } = 4;
    public string TgLightColor { get; set; } = "#FF2BD6";
    public int TgLightBrightness { get; set; } = 80;
    public bool TgKeyLight { get; set; } = true;
    public bool TgLightCycle { get; set; }
    public string[] TgSideMedia { get; set; } = ["", "", "", ""];
    public List<ClockFace> TgThemes { get; set; } = [];
    public string SelectedFaceId { get; set; } = "swiss";
    public bool ShowArtwork { get; set; } = true;
    public string TrackSource { get; set; } = "media";
    public bool MediaOnlySpotify { get; set; } = true;
    public string SpotifyClientId { get; set; } = "";
    public string UiTheme { get; set; } = "auto";
    public bool DeveloperMode { get; set; }
}

internal sealed class ClockFace
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public string Name { get; set; } = "Новый пак";
    public string Style { get; set; } = "custom";
    public Dictionary<string, string> Palette { get; set; } = new();
    public Dictionary<string, string> Chars { get; set; } = new();
    public ClockFace Copy() => new() { Name = Name, Style = Style, Palette = new(Palette), Chars = new(Chars) };
}

internal sealed class ProfileStore
{
    internal static readonly string Folder = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), Edition.ProfileName);
    private static readonly string ProfilePath = Path.Combine(Folder, "ui-settings.json");
    internal static readonly JsonSerializerOptions Json = new()
        { WriteIndented = true, PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    internal static readonly JsonSerializerOptions JsonWire = new()
        { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };

    public string? LoadError { get; private set; }
    public HubProfile Load()
    {
        try
        {
            if (File.Exists(ProfilePath))
                return JsonSerializer.Deserialize<HubProfile>(File.ReadAllText(ProfilePath), Json) ?? new();
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException)
        {
            if (e is JsonException)
            {
                try
                {
                    File.Move(ProfilePath, ProfilePath + "." + Guid.NewGuid().ToString("N") + ".bak");
                    LoadError = "Не удалось прочитать профиль. Копия сохранена в папке данных.";
                }
                catch (Exception backupError) when (backupError is IOException or UnauthorizedAccessException)
                {
                    LoadError = "Не удалось прочитать профиль или сохранить его копию.";
                }
            }
            else LoadError = "Не удалось открыть профиль. Проверьте доступ к папке данных.";
        }
        return new();
    }

    public void Save(HubProfile profile)
    {
        Directory.CreateDirectory(Folder);
        string temporary = ProfilePath + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllText(temporary, JsonSerializer.Serialize(profile, Json));
            File.Move(temporary, ProfilePath, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporary)) File.Delete(temporary);
        }
    }
}
