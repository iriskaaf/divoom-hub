using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace divoom_hub_winui3;

internal static class LegacyImport
{
    private static readonly string LegacyFolder = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DivoomHub");
    public static string ConfigPath => Path.Combine(LegacyFolder, "config.json");
    public static bool Available => File.Exists(ConfigPath);

    public static HubProfile Read(DeviceCatalog catalog)
    {
        var config = JsonNode.Parse(File.ReadAllText(ConfigPath))?.AsObject() ?? throw new JsonException();
        var oldThemes = config["tg_themes"] as JsonArray;
        var themeIndex = config["tg_theme"]?.GetValue<int>() ?? 1;
        config.Remove("tg_themes");
        if (config["tg_24h"] is JsonNode format24) config["tg24h"] = format24.DeepClone();
        var profile = config.Deserialize<HubProfile>(ProfileStore.JsonWire) ?? throw new JsonException();
        profile.TgToken = config["tg_token"]?.GetValue<string>()?.Trim() ?? "";
        if (profile.TgToken.Length > 32 || !profile.TgToken.All(char.IsAsciiDigit)) throw new JsonException();
        var styles = catalog.Styles.Select(x => x.Item1).ToHashSet();
        if (oldThemes is not null)
        {
            for (int i = 0; i < oldThemes.Count; i++)
            {
                if (oldThemes[i] is not JsonObject source || source["style"]?.GetValue<string>() is not string style ||
                    !styles.Contains(style)) continue;
                var face = new ClockFace { Style = style, Name = source["name"]?.GetValue<string>() ?? "Циферблат" };
                foreach (var (key, _, fallback) in catalog.Roles(style))
                    face.Palette[key] = source[key]?.GetValue<string>() ?? fallback;
                if (source["chars"] is JsonObject chars)
                    foreach (var (digit, path) in chars)
                        if (digit.Length == 1 && FacePacks.Digits.Contains(digit[0]) &&
                            path is JsonValue entry && entry.TryGetValue<string>(out var file))
                            face.Chars[digit] = file;
                if (i == themeIndex) profile.SelectedFaceId = face.Id;
                profile.TgThemes.Add(face);
            }
        }
        if (profile.TgThemes.Count == 0) profile.TgThemes = catalog.Faces;
        profile.TgSideMedia = profile.TgSideMedia.Concat(new[] { "", "", "", "" }).Take(4).ToArray();
        profile.OnboardingCompleted = true;
        return profile;
    }
}
