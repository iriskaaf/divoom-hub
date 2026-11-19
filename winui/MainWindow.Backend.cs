using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml.Controls;
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;

namespace divoom_hub_winui3;

public sealed partial class MainWindow
{
    private PythonBackend? _backend;
    private DispatcherQueueTimer? _backendTimer;
    private bool _previewBusy;
    private int _trackRevision;
    private string? _coverTrack;
    private string? _coverData;
    private string? _lastConfig;
    private readonly System.Threading.SemaphoreSlim _configLock = new(1, 1);
    private bool _closing;
    private bool _loadingBuiltins;
    internal bool Minimized { get; private set; }
    internal LiveState Live { get; } = new();
    internal event Action? LiveChanged;

    private void StartBackend()
    {
        _backend = new PythonBackend();
        _backend.Event += (name, data, device) => DispatcherQueue.TryEnqueue(() => Receive(name, data, device));
        _backend.Disconnected += () => DispatcherQueue.TryEnqueue(() =>
        {
            Live.Ready = false;
            foreach (var state in _deviceState.Values) { state.Online = false; state.Status = "Отключено"; }
            Live.BackendStatus = "Служба остановилась. Перезапустите Divoom Hub.";
            RefreshDeviceMenu();
            LiveChanged?.Invoke();
        });
        try
        {
            _backend.Start();
            _backendTimer = DispatcherQueue.CreateTimer();
            _backendTimer.Interval = TimeSpan.FromSeconds(4);
            _backendTimer.Tick += async (_, _) => { if (Live.Ready) { await SyncAsync(); await PreviewAsync(); } };
            _backendTimer.Start();
        }
        catch (Exception e) when (e is IOException or System.ComponentModel.Win32Exception)
        {
            Live.BackendStatus = "Python-бэкенд недоступен. Проверьте папку Backend.";
            Log(Live.BackendStatus);
            LiveChanged?.Invoke();
        }
    }

    private static JsonObject WireSettings(HubProfile profile)
    {
        var data = JsonSerializer.SerializeToNode(profile, ProfileStore.JsonWire)!.AsObject();
        data.Remove("devices");
        data["tg_24h"] = profile.Tg24h;
        data["tg_token"] = profile.TgToken;
        return data;
    }

    internal async Task SyncAsync()
    {
        await _configLock.WaitAsync();
        try { await SendConfigAsync(); }
        finally { _configLock.Release(); }
    }

    private async Task SendConfigAsync()
    {
        if (!Live.Ready || _backend is null || _closing) return;
        bool oldHub = OtherControllerRunning();
        bool changed = Live.DevicesPaused != oldHub;
        Live.DevicesPaused = oldHub;
        var data = new
        {
            music = new { Profile.ShowArtwork, Profile.TrackSource, Profile.MediaOnlySpotify, Profile.SpotifyClientId },
            devices = Profile.Devices.Select(device => new
            {
                device.Id, device.Kind, settings = WireSettings(device.Settings)
            }).ToArray(),
            devices_paused = oldHub || !Profile.OnboardingCompleted,
        };
        string sent = JsonSerializer.Serialize(data, ProfileStore.JsonWire);
        if (_lastConfig == sent) return;
        _lastConfig = sent;
        InvalidateGateFrames();
        try { await _backend.CallAsync("configure_all", data); }
        catch (Exception e) when (IsBackendError(e))
        {
            if (_lastConfig == sent) _lastConfig = null;
            Live.BackendStatus = "Не удалось передать настройки службе.";
            LiveChanged?.Invoke();
            return;
        }
        if (changed) LiveChanged?.Invoke();
        _ = PreviewAsync();
    }

    private void InvalidateGateFrames()
    {
        foreach (var device in Profile.Devices.Where(x => x.Kind == "gate")) State(device).PreviewMinute = -1;
    }

    internal async Task<JsonElement> CommandAsync(string command, object? args = null, DeviceEntry? device = null)
    {
        if (!Live.Ready || _backend is null || _closing) throw new BackendException("Служба Divoom Hub пока недоступна.");
        if ((command.StartsWith("probe_", StringComparison.Ordinal) || command.StartsWith("ditoo_", StringComparison.Ordinal)
            || command is "connect_ditoo" or "reconnect_gate") && OtherControllerRunning())
            throw new BackendException("Выйдите из другой версии Divoom Hub через трей, чтобы освободить устройства.");
        await SyncAsync();
        var payload = args is null ? new JsonObject() : JsonSerializer.SerializeToNode(args, ProfileStore.JsonWire)!.AsObject();
        if ((device ?? CurrentDevice) is DeviceEntry target) payload["device"] = target.Id;
        return await _backend.CallAsync(command, payload);
    }

    internal static bool IsBackendError(Exception e) =>
        e is BackendException or IOException or TimeoutException or InvalidOperationException;

    internal async Task RunCommand(string name, PageSurface page, object? args = null, DeviceEntry? device = null)
    {
        try { await CommandAsync(name, args, device); }
        catch (Exception e) when (IsBackendError(e))
        { page.Message(e is BackendException ? e.Message : "Служба не ответила.", InfoBarSeverity.Warning); }
    }

    internal async Task LoadBuiltinsAsync()
    {
        if (!Live.Ready || _loadingBuiltins || Live.Builtins is not null) return;
        _loadingBuiltins = true;
        try
        {
            var response = await CommandAsync("builtins");
            Live.Builtins = response.EnumerateObject().Select(x => (x.Name, x.Value.GetString()!)).ToArray();
            LiveChanged?.Invoke();
        }
        catch (Exception e) when (IsBackendError(e)) { Log("Список встроенных циферблатов недоступен."); }
        finally { _loadingBuiltins = false; }
    }

    internal async Task LoadThumbnailsAsync(DeviceEntry device)
    {
        if (!Live.Ready || _backend is null) return;
        var settings = device.Settings;
        var payload = new { settings.TgMode, settings.TgThemes };
        string key = JsonSerializer.Serialize(payload, ProfileStore.JsonWire);
        var state = State(device);
        if (state.ThumbnailKey == key) return;
        state.ThumbnailKey = key;
        try
        {
            var result = await _backend.CallAsync("thumbnails", payload);
            var images = await Task.WhenAll(result.EnumerateArray().Select(LiveState.DecodeAsync));
            if (state.ThumbnailKey != key) return;
            state.Thumbnails = images;
            LiveChanged?.Invoke();
        }
        catch (Exception e) when (IsBackendError(e) || e is FormatException or System.Runtime.InteropServices.COMException)
        {
            if (state.ThumbnailKey == key) state.ThumbnailKey = null;
            Log("Эскизы циферблатов недоступны.");
        }
    }

    private static bool OtherControllerRunning()
    {
        var names = Edition.Test ? new[] { "DivoomHub", "DivoomHub_TEST", "divoom-hub-winui3" }
                                 : new[] { "DivoomHub", "DivoomHub_TEST" };
        using var self = Process.GetCurrentProcess();
        foreach (var name in names)
        {
            var processes = Process.GetProcessesByName(name);
            try { if (processes.Any(p => p.Id != self.Id && p.SessionId == self.SessionId)) return true; }
            finally { foreach (var p in processes) p.Dispose(); }
        }
        return false;
    }

    internal void ShowWindow() { Minimized = false; AppWindow.Show(); Activate(); _ = PreviewAsync(); }
    internal void HideWindow() { Minimized = true; AppWindow.Hide(); }

    internal void StepFace(DeviceEntry target, int step)
    {
        var p = target.Settings;
        var faces = p.TgThemes;
        int index = (faces.IndexOf(target.Face) + step + faces.Count) % faces.Count;
        p.SelectedFaceId = faces[index].Id;
        SetGateModeFromTray(target, p.TgMode is "off" or "device" ? "clock" : p.TgMode);
    }

    internal void SetGateModeFromTray(DeviceEntry target, string mode)
    {
        target.Settings.TgMode = mode;
        Save();
        if (SetupHost.Content is null && _route == target.Id) Navigate(_route);
    }

    internal async Task QuitAsync()
    {
        if (_closing) return;
        if (_saveTimer.IsRunning) Save();
        _closing = true;
        _backendTimer?.Stop();
        HideWindow();
        _tray?.Hide();
        if (_backend is not null) await _backend.StopAsync();
        Close();
    }

    private async void Receive(string name, JsonElement data, string? deviceId)
    {
        if (_closing) return;
        try
        {
            var device = deviceId is null ? null : Profile.Devices.FirstOrDefault(x => x.Id == deviceId);
            if (deviceId is not null && device is null) return;
            var state = device is null ? null : State(device);
            switch (name)
            {
                case "ready":
                    Live.Ready = true;
                    Live.BackendStatus = "Служба запущена";
                    await SyncAsync();
                    break;
                case "ditoo" or "tg" when state is not null:
                    bool moved = state.Online != data[0].GetBoolean();
                    state.Online = data[0].GetBoolean();
                    state.Status = data[1].GetString()!;
                    state.PreviewMinute = -1;
                    if (name == "ditoo" && state.Online && string.Equals(device!.Address, data[2].GetString(), StringComparison.OrdinalIgnoreCase))
                    {
                        int port = data[3].GetInt32();
                        if (device.Settings.DitooPort != port) { device.Settings.DitooPort = port; SaveSoon(); }
                    }
                    if (moved) RefreshDeviceMenu();
                    _ = PreviewAsync();
                    break;
                case "tg_ip" when device is not null:
                    device.Settings.TgIp = data.GetString()!;
                    SaveSoon();
                    break;
                case "spotify":
                    Live.Music = data.GetString()!;
                    break;
                case "login":
                    Live.LoggedIn = data.GetBoolean();
                    break;
                case "track":
                    int trackRevision = ++_trackRevision;
                    Live.Track = data.ValueKind == JsonValueKind.Null ? "" : data.GetProperty("track_name").GetString()!;
                    Live.Artist = data.ValueKind == JsonValueKind.Null ? "" : data.GetProperty("artist_name").GetString()!;
                    Live.Playing = data.ValueKind != JsonValueKind.Null && data.GetProperty("is_playing").GetBoolean();
                    string? id = data.ValueKind == JsonValueKind.Null ? null : data.GetProperty("track_id").GetString();
                    if (_coverTrack != id) { Live.Cover = null; _coverTrack = null; _coverData = null; }
                    if (data.ValueKind != JsonValueKind.Null)
                    {
                        var encoded = data.GetProperty("cover");
                        string? coverData = encoded.ValueKind == JsonValueKind.String ? encoded.GetString() : null;
                        if (coverData is not null && (Live.Cover is null || _coverData != coverData))
                        {
                            var cover = await LiveState.DecodeAsync(encoded);
                            if (trackRevision != _trackRevision) return;
                            if (cover is not null) { Live.Cover = cover; _coverTrack = id; _coverData = coverData; }
                        }
                    }
                    InvalidateGateFrames();
                    _ = PreviewAsync();
                    break;
                case "display" when state is not null:
                    int revision = ++state.Revision;
                    var frame = await LiveState.DecodeAsync(data);
                    if (revision != state.Revision) return;
                    state.Frame = frame;
                    break;
                case "tg_screens" when state is not null:
                    state.PreviewMinute = -1;
                    _ = PreviewAsync();
                    return;
                case "log":
                    Log(data.GetString()!);
                    break;
            }
            LiveChanged?.Invoke();
        }
        catch (Exception e) when (e is FormatException or InvalidOperationException or System.Runtime.InteropServices.COMException)
        { Log("Не удалось отобразить событие службы."); }
    }

    internal async Task PreviewAsync()
    {
        if (_previewBusy || _closing || Minimized || !Live.Ready || SetupHost.Content is not null) return;
        var devices = Profile.Devices.Where(d => d.Kind == "gate" &&
            (CurrentDevice == d || (_route == "home" && State(d).Online))).ToArray();
        if (devices.Length == 0) return;
        _previewBusy = true;
        try
        {
            long minute = DateTime.Now.Ticks / TimeSpan.TicksPerMinute;
            await Task.WhenAll(devices.Select(async device =>
            {
                var state = State(device);
                if (state.PreviewMinute == minute) return;
                state.PreviewMinute = minute;
                try
                {
                    var frames = await _backend!.CallAsync("preview", new { device = device.Id });
                    state.Frames = await Task.WhenAll(frames.EnumerateArray().Select(LiveState.DecodeAsync));
                }
                catch { state.PreviewMinute = -1; throw; }
            }));
            LiveChanged?.Invoke();
        }
        catch (Exception e) when (IsBackendError(e) || e is FormatException or System.Runtime.InteropServices.COMException)
        { Log("Предпросмотр Times Gate недоступен."); }
        finally { _previewBusy = false; }
    }
}
