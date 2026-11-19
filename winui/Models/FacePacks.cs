using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text.Json;

namespace divoom_hub_winui3;

internal static class FacePacks
{
    internal static readonly string[] MediaExtensions = [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"];
    internal const string Digits = "0123456789:";
    private const int MaxImageBytes = 20 * 1024 * 1024;

    private sealed record Manifest(int Format, string Name, string Style, string Color, string Bg,
        Dictionary<string, string> Chars, Dictionary<string, string> Palette);

    public static ClockFace Import(string archive, DeviceCatalog catalog)
    {
        using var zip = ZipFile.OpenRead(archive);
        var entry = zip.GetEntry("manifest.json");
        if (entry is null || entry.Length > 65536) throw new InvalidDataException("Invalid manifest");
        using var data = entry.Open();
        var manifest = JsonSerializer.Deserialize<Manifest>(data, ProfileStore.Json);
        if (manifest is not { Format: 1, Chars: not null }) throw new InvalidDataException("Invalid pack format");
        string name = string.IsNullOrWhiteSpace(manifest.Name) ? "Импортированный пак" : manifest.Name;
        var face = new ClockFace { Name = name[..Math.Min(40, name.Length)],
            Style = catalog.Styles.Any(s => s.Item1 == manifest.Style) ? manifest.Style : "custom" };
        foreach (var role in catalog.Roles(face.Style))
            face.Palette[role.Key] = manifest.Palette?.GetValueOrDefault(role.Key) ?? role.Default;
        string folder = Path.Combine(ProfileStore.Folder, "packs", face.Id);
        foreach (char digit in Digits)
        {
            string key = digit.ToString();
            if (!manifest.Chars.TryGetValue(key, out string? file) || file is null) continue;
            var image = zip.GetEntry(file);
            string ext = Path.GetExtension(file).ToLowerInvariant();
            if (image is null || image.Length > MaxImageBytes || !MediaExtensions.Contains(ext))
                throw new InvalidDataException("Invalid pack image");
            Directory.CreateDirectory(folder);
            string target = Path.Combine(folder, FileStem(digit) + ext);
            using var source = image.Open();
            using var output = File.Create(target);
            source.CopyTo(output);
            face.Chars[key] = target;
        }
        return face;
    }

    public static void Export(ClockFace face, string target)
    {
        string temp = target + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            using (var zip = ZipFile.Open(temp, ZipArchiveMode.Create))
            {
                var chars = new Dictionary<string, string>();
                foreach (var (key, path) in face.Chars)
                {
                    if (key.Length != 1 || !Digits.Contains(key[0]) || !File.Exists(path)) continue;
                    string extension = Path.GetExtension(path).ToLowerInvariant();
                    if (!MediaExtensions.Contains(extension) || new FileInfo(path).Length > MaxImageBytes) continue;
                    string name = FileStem(key[0]) + extension;
                    zip.CreateEntryFromFile(path, name);
                    chars[key] = name;
                }
                var manifest = new Manifest(1, face.Name, face.Style, face.Palette.GetValueOrDefault("color", "#FFFFFF"),
                    face.Palette.GetValueOrDefault("bg", "#000000"), chars, face.Palette);
                using var output = zip.CreateEntry("manifest.json").Open();
                JsonSerializer.Serialize(output, manifest, ProfileStore.Json);
            }
            File.Move(temp, target, overwrite: true);
        }
        finally { if (File.Exists(temp)) File.Delete(temp); }
    }

    private static string FileStem(char digit) => digit == ':' ? "char_colon" : "char_" + digit;
}
