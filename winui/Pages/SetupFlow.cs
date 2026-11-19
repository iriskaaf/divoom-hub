using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using System;
using System.Collections.Generic;
using System.Linq;

namespace divoom_hub_winui3;

internal sealed class SetupFlow(MainWindow window, bool adding)
{
    private readonly Dictionary<string, DeviceEntry> _drafts = new();
    private readonly List<string> _steps = [];
    private int _step;
    private bool _ditoo;
    private bool _gate;
    private string _source = window.Profile.TrackSource;

    public void Start()
    {
        var page = new PageSurface(adding ? "Добавить устройство" : "Добро пожаловать в Divoom Hub",
            adding ? () => window.FinishSetup(true) : null);
        page.CenterSetup();
        var introduction = Form.Text(Edition.Test && !adding && window.Profile.Devices.Count > 0
            ? "Настройки устройств загружены. Можно продолжить или добавить другие устройства."
            : "Выберите устройства, которые хотите подключить.");
        introduction.TextAlignment = TextAlignment.Center;
        page.Add(introduction);
        var choices = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12, HorizontalAlignment = HorizontalAlignment.Center };
        var gate = Form.Tile("Times Gate", "Wi-Fi · часы и подсветка", "times-gate.png", _gate);
        var ditoo = Form.Tile("Ditoo Pro", "Bluetooth · обложки", "ditoo.png", _ditoo);
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, HorizontalAlignment = HorizontalAlignment.Center };
        var next = Form.Button("Продолжить", Begin, true);
        void Update()
        {
            _gate = gate.IsChecked == true;
            _ditoo = ditoo.IsChecked == true;
            next.IsEnabled = _gate || _ditoo;
        }
        gate.Click += (_, _) => Update();
        ditoo.Click += (_, _) => Update();
        Update();
        choices.Children.Add(gate);
        choices.Children.Add(ditoo);
        page.Add(choices);
        if (!adding) buttons.Children.Add(Form.Button(window.Profile.Devices.Count == 0 ? "Пропустить" : "Оставить текущие устройства",
            () => { _gate = _ditoo = false; Begin(); }));
        buttons.Children.Add(next);
        page.Add(buttons);
        window.ShowSetup(page);
    }

    private void Begin()
    {
        _steps.Clear();
        if (_gate) _steps.Add("gate");
        if (_ditoo) _steps.Add("ditoo");
        if (!adding) _steps.Add("music");
        _step = 0;
        ShowStep();
    }

    private void Back()
    {
        if (_step == 0) Start();
        else { _step--; ShowStep(); }
    }

    private void ShowStep()
    {
        string step = _steps[_step];
        string title = step == "gate" ? "Times Gate" : step == "ditoo" ? "Ditoo Pro" : "Музыка";
        var page = new PageSurface($"Шаг {_step + 1} из {_steps.Count} · {title}", Back);
        if (step == "music")
        {
            page.CenterSetup();
            var instruction = Form.Text("Выберите источник трека и обложки.");
            instruction.TextAlignment = TextAlignment.Center;
            page.Add(instruction);
            var options = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12, HorizontalAlignment = HorizontalAlignment.Center };
            var media = Form.Tile("Медиасессия Windows", "Музыка на этом ПК · без входа", "media-session.svg", _source == "media");
            var api = Form.Tile("Spotify Web API", "Нужен вход в Spotify", "spotify.svg", _source == "api");
            void Select(string source) { _source = source; media.IsChecked = source == "media"; api.IsChecked = source == "api"; }
            media.Click += (_, _) => Select("media");
            api.Click += (_, _) => Select("api");
            options.Children.Add(media);
            options.Children.Add(api);
            page.Add(options);
            var next = Form.Button("Продолжить", Advance, true);
            next.HorizontalAlignment = HorizontalAlignment.Center;
            page.Add(next);
        }
        else
        {
            if (!_drafts.TryGetValue(step, out var device))
            {
                string name = title;
                for (int n = 2; window.Profile.Devices.Any(x => x.Name == name); n++) name = $"{title} {n}";
                _drafts[step] = device = new DeviceEntry
                {
                    Name = name, Kind = step,
                    Settings = new HubProfile { DeviceSchema = 1, TgThemes = window.Catalog.Faces }
                };
            }
            var p = device.Settings;
            var field = new TextBox { Text = device.Name, MaxLength = 40, MinWidth = 170 };
            page.Add(Form.Row("Название", "Имя в боковом меню", field));
            field.TextChanged += (_, _) => device.Name = field.Text.Trim();
            page.Add(DevicePages.ConnectionFields(window, step, p.DitooAddress, p.TgIp, p.TgToken, p.TgHardware,
                (address, ip, token, port, mac, hardware) =>
            {
                if (device.Name.Length == 0) { page.Message("Введите название устройства.", InfoBarSeverity.Warning); return; }
                p.DitooAddress = address;
                p.DitooPort = port;
                p.TgIp = ip;
                p.TgMac = mac;
                p.TgHardware = hardware;
                p.TgToken = token;
                Advance();
            }, "Подключить и продолжить"));
        }
        window.ShowSetup(page);
    }

    private void Advance()
    {
        if (_step + 1 < _steps.Count) { _step++; ShowStep(); return; }
        var profile = window.Profile;
        var added = _steps.Where(_drafts.ContainsKey).Select(step => _drafts[step]).ToArray();
        foreach (var device in added.Where(x => x.Kind == "gate"))
        {
            string token = device.Settings.TgToken;
            device.Settings.TgToken = "";
            bool saved = window.StoreLocalToken(device, token, window.ActivePage!);
            device.Settings.TgToken = token;
            if (!saved) return;
        }

        bool previous = profile.OnboardingCompleted;
        string originalSource = profile.TrackSource;
        profile.Devices.AddRange(added);
        profile.TrackSource = _source;
        profile.OnboardingCompleted = true;
        if (!window.Save())
        {
            foreach (var device in added) profile.Devices.Remove(device);
            profile.OnboardingCompleted = previous;
            profile.TrackSource = originalSource;
            return;
        }
        window.FinishSetup(adding);
        foreach (var device in added.Where(x => x.Kind == "ditoo"))
            _ = window.RunCommand("connect_ditoo", window.ActivePage!, device: device);
    }
}
