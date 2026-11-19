using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Media;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace divoom_hub_winui3;

public sealed partial class MainWindow : Window
{
    private readonly ProfileStore _store = new();
    internal readonly DeviceCatalog Catalog = new();
    internal HubProfile Profile { get; }
    internal readonly List<string> Journal = [];
    private readonly Dictionary<string, NavigationViewItem> _deviceMenu = new();
    private readonly Dictionary<string, DeviceLive> _deviceState = new();
    private string _route = "";
    private bool _selecting;
    private readonly TrayIcon? _tray;
    private readonly bool _persist;
    private readonly Microsoft.UI.Dispatching.DispatcherQueueTimer _saveTimer;
    internal DeviceEntry? CurrentDevice => Profile.Devices.FirstOrDefault(d => d.Id == _route);
    internal bool TrayDark => Root.ActualTheme == ElementTheme.Dark;
    internal HubProfile DeviceSettings => CurrentDevice?.Settings ?? Profile;
    internal ClockFace CurrentFace => DeviceSettings.TgThemes.FirstOrDefault(f => f.Id == DeviceSettings.SelectedFaceId) ?? DeviceSettings.TgThemes[0];

    public MainWindow() : this(null) { }

    internal MainWindow(HubProfile? previewProfile)
    {
        _persist = previewProfile is null;
        Profile = previewProfile ?? LoadProfile();
        if (Profile.TgThemes.Count == 0) Profile.TgThemes = Catalog.Faces;
        if (Profile.DeviceSchema < 1)
        {
            if (Profile.TimesgateEnabled) Profile.Devices.Add(DeviceEntry.FromLegacy("gate", Profile));
            if (Profile.DitooEnabled) Profile.Devices.Add(DeviceEntry.FromLegacy("ditoo", Profile));
            if (_persist && !Edition.Test && Profile.Devices.FirstOrDefault(d => d.Kind == "gate") is DeviceEntry gate)
            {
                try { LocalTokenStore.Save(LocalTokenStore.Read(), gate.Id); }
                catch (Exception) { Log("Не удалось перенести LocalToken."); }
            }
            Profile.DeviceSchema = 1;
            if (_persist && !Edition.Test && Profile.Devices.Count > 0)
            {
                try { _store.Save(Profile); }
                catch (Exception) { Log("Не удалось сохранить перенесённый профиль."); }
            }
        }
        foreach (var device in Profile.Devices)
        {
            if (device.Settings.TgThemes.Count == 0) device.Settings.TgThemes = Catalog.Faces;
            if (_persist && !Edition.Test && device.Kind == "gate")
            {
                try { device.Settings.TgToken = LocalTokenStore.Read(device.Id); }
                catch (Exception) { Log("Не удалось прочитать LocalToken."); }
            }
        }

        InitializeComponent();
        _saveTimer = DispatcherQueue.CreateTimer();
        _saveTimer.Interval = TimeSpan.FromMilliseconds(350);
        _saveTimer.IsRepeating = false;
        _saveTimer.Tick += (_, _) => Save();
        Closed += (_, _) => { if (_saveTimer.IsRunning) Save(); };
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(HubTitleBar);
        if (Edition.Test) Title = HubTitleBar.Title = "Divoom Hub · TEST";
        AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory, "Assets", "icon.ico"));
        AppWindow.Resize(new Windows.Graphics.SizeInt32(1080, 800));
        ApplyTheme();
        Log("Интерфейс запущен");
        Navigate("home");
        if (!Profile.OnboardingCompleted) StartSetup(false);
        if (_persist)
        {
            _tray = new TrayIcon(this);
            StartBackend();
        }
    }

    private HubProfile LoadProfile()
    {
        if (!Edition.Test) return _store.Load();
        HubProfile profile;
        try { profile = LegacyImport.Available ? LegacyImport.Read(Catalog) : new(); }
        catch (Exception)
        {
            profile = new();
            Log("Не удалось автоматически прочитать старый профиль.");
        }
        profile.OnboardingCompleted = false;
        return profile;
    }

    internal DeviceLive State(DeviceEntry device)
    {
        if (!_deviceState.TryGetValue(device.Id, out var state)) _deviceState[device.Id] = state = new();
        return state;
    }

    internal void ApplyTheme() => Root.RequestedTheme = Profile.UiTheme switch
    {
        "light" => ElementTheme.Light, "dark" => ElementTheme.Dark, _ => ElementTheme.Default
    };

    internal bool Save()
    {
        _saveTimer.Stop();
        if (!_persist) return true;
        try { _store.Save(Profile); _ = SyncAsync(); return true; }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            Log("Не удалось сохранить настройки");
            ActivePage?.Message("Не удалось сохранить настройки на диске.", InfoBarSeverity.Error);
            return false;
        }
    }

    internal void SaveSoon() { _saveTimer.Stop(); _saveTimer.Start(); }

    internal void Log(string message)
    {
        if (Journal.Count >= 200) Journal.RemoveAt(0);
        Journal.Add($"{DateTime.Now:HH:mm:ss}  {message}");
    }

    internal void RefreshDeviceMenu()
    {
        var entries = Profile.Devices.OrderByDescending(d => State(d).Online).ToArray();
        foreach (var id in _deviceMenu.Keys.Where(id => !entries.Any(d => d.Id == id)).ToArray())
            _deviceMenu.Remove(id);
        foreach (var device in entries)
        {
            if (!_deviceMenu.TryGetValue(device.Id, out var item))
            {
                _deviceMenu[device.Id] = item = new NavigationViewItem
                {
                    Tag = device.Id, Icon = new FontIcon { Glyph = device.Kind == "gate" ? "\uE823" : "\uE702" },
                    InfoBadge = new InfoBadge { Width = 10, Height = 10, CornerRadius = new CornerRadius(5) }
                };
            }
            var state = State(device);
            item.Content = device.Name;
            item.InfoBadge.Background = StatusColor(state.Online);
            AutomationProperties.SetHelpText(item, state.Status);
        }
        DeviceSeparator.Visibility = entries.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        var desired = entries.Select(d => (object)_deviceMenu[d.Id]).ToArray();
        if (Navigation.MenuItems.Skip(2).SequenceEqual(desired)) return;
        _selecting = true;
        while (Navigation.MenuItems.Count > 2) Navigation.MenuItems.RemoveAt(2);
        foreach (var item in desired) Navigation.MenuItems.Add(item);
        if (_deviceMenu.TryGetValue(_route, out var selected)) Navigation.SelectedItem = selected;
        _selecting = false;
    }

    internal static SolidColorBrush StatusColor(bool online) => ClockPreview.Brush(online ? "#61CF5C" : "#E45555");

    internal void Navigate(string route)
    {
        var device = Profile.Devices.FirstOrDefault(d => d.Id == route || d.Kind == route);
        _route = device?.Id ?? route;
        RefreshDeviceMenu();
        _selecting = true;
        Navigation.SelectedItem = device is not null ? _deviceMenu[device.Id] : route switch
        {
            "settings" => SettingsItem, "about" => AboutItem, _ => HomeItem
        };
        _selecting = false;
        Show(device is not null ? device.Kind == "gate" ? GatePages.Create(this) : DevicePages.Ditoo(this, device) : route switch
        {
            "settings" => SettingsPages.Settings(this),
            "about" => SettingsPages.About(),
            _ => SettingsPages.Home(this, _store.LoadError)
        });
        _ = PreviewAsync();
    }

    internal void Show(PageSurface page) => PageHost.Content = page;
    internal PageSurface? ActivePage => (SetupHost.Content ?? PageHost.Content) as PageSurface;

    internal bool StoreLocalToken(DeviceEntry device, string token, PageSurface page)
    {
        if (!_persist || Edition.Test || token == device.Settings.TgToken) return true;
        try { LocalTokenStore.Save(token, device.Id); return true; }
        catch (Exception)
        {
            page.Message("Windows не удалось сохранить LocalToken.", InfoBarSeverity.Error);
            return false;
        }
    }

    internal void RemoveDevice(DeviceEntry device)
    {
        int index = Profile.Devices.IndexOf(device);
        if (index < 0) return;
        Profile.Devices.RemoveAt(index);
        if (!Save()) { Profile.Devices.Insert(index, device); return; }
        _deviceState.Remove(device.Id);
        if (_persist && !Edition.Test && device.Kind == "gate")
        {
            try { LocalTokenStore.Save("", device.Id); }
            catch (Exception) { Log("Не удалось удалить сохранённый LocalToken."); }
        }
        Navigate("settings");
    }

    internal void ShowSetup(PageSurface page)
    {
        Navigation.Visibility = Visibility.Collapsed;
        SetupHost.Content = page;
        SetupHost.Visibility = Visibility.Visible;
    }

    internal void StartSetup(bool adding) => new SetupFlow(this, adding).Start();

    internal void FinishSetup(bool adding)
    {
        SetupHost.Content = null;
        SetupHost.Visibility = Visibility.Collapsed;
        Navigation.Visibility = Visibility.Visible;
        Navigate(adding ? "settings" : "home");
    }

    private void NavigationChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (!_selecting && args.SelectedItem is NavigationViewItem { Tag: string route } && route != _route)
            Navigate(route);
    }
}
