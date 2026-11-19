using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace divoom_hub_winui3;

internal sealed class DeviceCatalog
{
    private readonly JsonElement _data;
    public DeviceCatalog()
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Assets", "catalog.json")));
        _data = document.RootElement.Clone();
    }

    public List<ClockFace> Faces => _data.GetProperty("faces").EnumerateArray().Select(face =>
    {
        string style = face.GetProperty("style").GetString()!;
        var result = new ClockFace { Id = style, Name = face.GetProperty("name").GetString()!, Style = style };
        foreach (var role in Roles(style))
            result.Palette[role.Key] = face.TryGetProperty(role.Key, out var value) ? value.GetString()! : role.Default;
        return result;
    }).ToList();

    public IEnumerable<(string Key, string Label, string Default)> Roles(string style) =>
        _data.GetProperty("roles").GetProperty(style).EnumerateArray()
            .Select(x => (x[0].GetString()!, x[1].GetString()!, x[2].GetString()!));

    public (string, string)[] Styles => Options("styles");
    public (string, string)[] Idle => Options("idle");
    public (string, string)[] Builtin => Options("builtin");
    public (int Id, string Label, bool TakesColor)[] Effects(int zone) =>
        _data.GetProperty(zone == 2 ? "back" : "edge").EnumerateArray()
            .Select(x => (x[0].GetInt32(), x[1].GetString()!, x[2].GetBoolean())).ToArray();

    private (string, string)[] Options(string key) => _data.GetProperty(key).EnumerateObject()
        .Select(x => (x.Name, x.Value.GetString()!)).ToArray();
}
