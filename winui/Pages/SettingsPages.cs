using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using System;
using System.IO;
using System.Linq;
using Windows.System;

namespace divoom_hub_winui3;

internal static class SettingsPages
{
    public static PageSurface Home(MainWindow window, string? loadError)
    {
        var p = window.Profile;
        var page = new PageSurface("Главная");
        if (loadError is not null) page.Message(loadError, InfoBarSeverity.Warning);
        var player = Form.Stack(14);
        var top = new Grid { ColumnSpacing = 14 };
        top.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        top.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var label = Form.Text("Сейчас играет", "BodyStrongTextBlockStyle");
        label.VerticalAlignment = VerticalAlignment.Center;
        top.Children.Add(label);
        var source = Form.Combo("", p.TrackSource, [("media", "Медиасессия Windows"), ("api", "Spotify Web API")],
            value => { p.TrackSource = value; window.Save(); });
        source.Header = null;
        Grid.SetColumn(source, 1);
        top.Children.Add(source);
        player.Children.Add(top);

        var layout = new Grid { ColumnSpacing = 16 };
        layout.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        layout.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        var cover = new Image { Width = 124, Height = 124, Stretch = Microsoft.UI.Xaml.Media.Stretch.UniformToFill };
        var art = Form.Card(cover);
        art.Padding = new Thickness(0);
        layout.Children.Add(art);
        var details = Form.Stack(5);
        details.VerticalAlignment = VerticalAlignment.Center;
        var track = Form.Text("", "SubtitleTextBlockStyle");
        var artist = Form.Text("");
        var status = Form.Text("", "CaptionTextBlockStyle");
        var controls = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        Button MediaButton(Symbol symbol, string name, string command)
        {
            var button = Form.Button("", () => _ = window.RunCommand("media_" + command, page));
            button.Content = new SymbolIcon(symbol);
            button.Width = button.Height = 40;
            Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(button, name);
            ToolTipService.SetToolTip(button, name);
            return button;
        }
        var previous = MediaButton(Symbol.Previous, "Предыдущий трек", "previous");
        var play = MediaButton(Symbol.Play, "Воспроизведение или пауза", "toggle");
        var next = MediaButton(Symbol.Next, "Следующий трек", "next");
        controls.Children.Add(previous); controls.Children.Add(play); controls.Children.Add(next);
        var account = Form.Button("Настроить Spotify", () => window.Navigate("settings"));
        details.Children.Add(track); details.Children.Add(artist); details.Children.Add(status);
        details.Children.Add(controls); details.Children.Add(account);
        Grid.SetColumn(details, 1);
        layout.Children.Add(details);
        player.Children.Add(layout);
        page.Add(Form.Card(player));
        page.Observe(window, () =>
        {
            track.Text = p.ShowArtwork ? (window.Live.Track.Length > 0 ? window.Live.Track : "Ничего не играет") : "Отслеживание выключено";
            artist.Text = window.Live.Artist;
            artist.Visibility = artist.Text.Length == 0 || !p.ShowArtwork ? Visibility.Collapsed : Visibility.Visible;
            status.Text = window.Live.DevicesPaused ? "Другая версия Divoom Hub управляет устройствами."
                : window.Live.Ready ? window.Live.Music : window.Live.BackendStatus;
            cover.Source = p.ShowArtwork ? window.Live.Cover : null;
            art.Visibility = cover.Source is null ? Visibility.Collapsed : Visibility.Visible;
            controls.Visibility = p.TrackSource == "media" ? Visibility.Visible : Visibility.Collapsed;
            bool canControl = window.Live.Ready && window.Live.Track.Length > 0 && p.ShowArtwork;
            previous.IsEnabled = play.IsEnabled = next.IsEnabled = canControl;
            ((SymbolIcon)play.Content).Symbol = window.Live.Playing ? Symbol.Pause : Symbol.Play;
            account.Visibility = p.TrackSource == "api" && !window.Live.LoggedIn ? Visibility.Visible : Visibility.Collapsed;
        });
        foreach (var device in p.Devices)
        {
            var state = window.State(device);
            var content = Form.Section(device.Name);
            var frame = new Image { Width = 112, Height = 112, HorizontalAlignment = HorizontalAlignment.Left };
            var screens = new ContentControl { HorizontalContentAlignment = HorizontalAlignment.Stretch };
            if (device.Kind == "gate") content.Children.Add(screens);
            else content.Children.Add(frame);
            content.Children.Add(Form.Button("Открыть", () => window.Navigate(device.Id)));
            var card = Form.Card(content);
            page.Add(card);
            object? last = null;
            page.Observe(window, () =>
            {
                card.Visibility = state.Online ? Visibility.Visible : Visibility.Collapsed;
                if (!state.Online) return;
                if (device.Kind == "gate")
                {
                    if (ReferenceEquals(last, state.Frames) && screens.Content is not null) return;
                    last = state.Frames;
                    screens.Content = state.Frames.Any(x => x is not null)
                        ? ClockPreview.FromFrames(state.Frames, 82)
                        : ClockPreview.Create(device.Face, device.Settings.TgMode, device.Settings.Tg24h, device.Settings.TgSideMedia);
                }
                else
                {
                    frame.Source = state.Frame;
                    frame.Visibility = frame.Source is null ? Visibility.Collapsed : Visibility.Visible;
                }
            });
        }
        return page;
    }

    public static PageSurface Settings(MainWindow window)
    {
        var p = window.Profile;
        var page = new PageSurface("Настройки");
        var devices = Form.Section("Устройства");
        var tiles = new VariableSizedWrapGrid { Orientation = Orientation.Horizontal, ItemWidth = 146, ItemHeight = 146 };
        foreach (var device in p.Devices)
        {
            var state = window.State(device);
            var tile = Form.Tile(device.Name, "Отключено", device.Kind == "gate" ? "times-gate.png" : "ditoo.png", false, 134);
            tile.Click += (_, _) =>
            {
                tile.IsChecked = false;
                window.Show(DevicePages.Connection(window, device, () => window.Navigate("settings")));
            };
            var rim = new Border { Child = tile, Width = 136, Height = 136, BorderThickness = new Thickness(1.5), CornerRadius = new CornerRadius(7) };
            var tileText = ((StackPanel)tile.Content).Children.OfType<TextBlock>().Last();
            page.Observe(window, () =>
            {
                rim.BorderBrush = MainWindow.StatusColor(state.Online);
                tileText.Text = state.Online ? "Подключено" : "Отключено";
                ToolTipService.SetToolTip(tile, state.Status);
            });
            tiles.Children.Add(rim);
        }
        var add = Form.Button("", () => window.StartSetup(true));
        add.Width = 136; add.Height = 136;
        var addContent = Form.Stack(10);
        addContent.Children.Add(new SymbolIcon(Symbol.Add));
        addContent.Children.Add(Form.Text("Добавить устройство", "CaptionTextBlockStyle"));
        add.Content = addContent;
        tiles.Children.Add(add);
        devices.Children.Add(tiles);
        page.Add(devices);

        var music = Form.Section("Музыка");
        var fields = Form.Stack();
        var api = Form.Stack();
        var session = Form.Toggle("Только Spotify", p.MediaOnlySpotify, value => { p.MediaOnlySpotify = value; window.Save(); });
        var client = new TextBox { Header = "Client ID", Text = p.SpotifyClientId };
        client.LostFocus += (_, _) => { if (client.Text.Trim() != p.SpotifyClientId) { p.SpotifyClientId = client.Text.Trim(); window.Save(); } };
        api.Children.Add(client);
        api.Children.Add(Form.Text("Redirect URI  ·  http://127.0.0.1:8888/callback", "CaptionTextBlockStyle"));
        api.Children.Add(Form.Button("Копировать Redirect URI", () =>
        {
            var data = new Windows.ApplicationModel.DataTransfer.DataPackage();
            data.SetText("http://127.0.0.1:8888/callback");
            Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(data);
        }));
        var login = new Button { Content = "Войти в Spotify" };
        login.Click += async (_, _) =>
        {
            p.SpotifyClientId = client.Text.Trim();
            if (!window.Live.LoggedIn && p.SpotifyClientId.Length == 0)
            { page.Message("Введите Client ID.", InfoBarSeverity.Warning); return; }
            window.Save();
            await window.RunCommand(window.Live.LoggedIn ? "spotify_logout" : "spotify_login", page);
        };
        page.Observe(window, () => login.Content = window.Live.LoggedIn ? "Выйти из Spotify" : "Войти в Spotify");
        api.Children.Add(login);
        void UpdateSource()
        {
            api.Visibility = p.TrackSource == "api" ? Visibility.Visible : Visibility.Collapsed;
            session.Visibility = p.TrackSource == "media" ? Visibility.Visible : Visibility.Collapsed;
            fields.Visibility = p.ShowArtwork ? Visibility.Visible : Visibility.Collapsed;
        }
        music.Children.Add(Form.Toggle("Следить за музыкой", p.ShowArtwork, value => { p.ShowArtwork = value; UpdateSource(); window.Save(); }));
        var musicStatus = Form.Text(window.Live.Music, "CaptionTextBlockStyle");
        page.Observe(window, () => musicStatus.Text = window.Live.Ready ? window.Live.Music : window.Live.BackendStatus);
        fields.Children.Add(musicStatus);
        fields.Children.Add(Form.Combo("Откуда брать трек и обложку", p.TrackSource,
            [("media", "Медиасессия Windows"), ("api", "Spotify Web API")],
            value => { p.TrackSource = value; UpdateSource(); window.Save(); }));
        fields.Children.Add(session);
        fields.Children.Add(api);
        music.Children.Add(fields);
        UpdateSource();
        page.Add(Form.Card(music));

        var appearance = Form.Section("Внешний вид");
        appearance.Children.Add(Form.Combo("Тема", p.UiTheme,
            [("auto", "Как в Windows"), ("light", "Светлая"), ("dark", "Тёмная")],
            value => { p.UiTheme = value; window.ApplyTheme(); window.Save(); }));
        page.Add(Form.Card(appearance));

        var startup = Form.Section("Запуск");
        var autostart = new ToggleSwitch { Header = "Запускать вместе с Windows", IsOn = !Edition.Test && Startup.Enabled, IsEnabled = !Edition.Test,
            OnContent = "Вкл.", OffContent = "Выкл." };
        bool resetting = false;
        autostart.Toggled += (_, _) =>
        {
            if (resetting) return;
            try { Startup.Set(autostart.IsOn); }
            catch (Exception)
            {
                page.Message("Не удалось изменить автозапуск.", InfoBarSeverity.Error);
                resetting = true;
                autostart.IsOn = Startup.Enabled;
                resetting = false;
            }
        };
        startup.Children.Add(autostart);
        page.Add(Form.Card(startup));

        var developer = Form.Section("Для разработчиков");
        var extra = Form.Stack();
        developer.Children.Add(Form.Toggle("Режим разработчика", p.DeveloperMode, value =>
        { p.DeveloperMode = value; extra.Visibility = value ? Visibility.Visible : Visibility.Collapsed; window.Save(); }));
        extra.Visibility = p.DeveloperMode ? Visibility.Visible : Visibility.Collapsed;
        extra.Children.Add(Form.Button("Журнал", () => window.Show(Log(window))));
        var folder = Form.Button("Открыть папку данных", null);
        folder.IsEnabled = true;
        folder.Click += async (_, _) =>
        {
            try
            {
                Directory.CreateDirectory(ProfileStore.Folder);
                await Launcher.LaunchFolderAsync(await Windows.Storage.StorageFolder.GetFolderFromPathAsync(ProfileStore.Folder));
            }
            catch (Exception) { page.Message("Не удалось открыть папку данных.", InfoBarSeverity.Warning); }
        };
        extra.Children.Add(folder);
        developer.Children.Add(extra);
        page.Add(Form.Card(developer));
        return page;
    }

    private static PageSurface Log(MainWindow window)
    {
        var page = new PageSurface("Журнал", () => window.Navigate("settings"));
        var lines = new TextBlock { TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true };
        page.Observe(window, () => lines.Text = string.Join(Environment.NewLine, window.Journal.AsEnumerable().Reverse()));
        page.Add(lines);
        return page;
    }

    public static PageSurface About()
    {
        var page = new PageSurface("О программе");
        var info = Form.Section("Divoom Hub");
        var logo = Form.Image("ms-appx:///Assets/logo.png", 56);
        logo.HorizontalAlignment = HorizontalAlignment.Left;
        info.Children.Insert(0, logo);
        info.Children.Add(Form.Text("C# · WinUI 3"));
        page.Add(Form.Card(info));
        var credits = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10 };
        foreach (var (name, detail, icon) in new[] {
            ("iriskaaf", "Разработчик", Symbol.Contact), ("WinUI 3", "Windows App SDK · MIT", Symbol.Library),
            ("Divoom", "Ditoo Pro · Times Gate", Symbol.Remote) })
        {
            var tile = Form.Stack();
            tile.Children.Add(new SymbolIcon(icon) { HorizontalAlignment = HorizontalAlignment.Left });
            tile.Children.Add(Form.Text(name, "BodyStrongTextBlockStyle"));
            tile.Children.Add(Form.Text(detail, "CaptionTextBlockStyle"));
            var card = Form.Card(tile);
            card.Width = 145;
            card.Height = 128;
            credits.Children.Add(card);
        }
        page.Add(new ScrollViewer { Content = credits, HorizontalScrollMode = ScrollMode.Enabled, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollMode = ScrollMode.Disabled });
        var components = Form.Section("Компоненты и лицензии");
        var componentGrid = new VariableSizedWrapGrid { Orientation = Orientation.Horizontal, ItemWidth = 136, ItemHeight = 136 };
        foreach (var (component, license, symbol) in new[] {
            (".NET", "MIT", Symbol.Setting), ("WinUI 3", "MIT", Symbol.Library), ("Python", "PSF 2.0", Symbol.Document),
            ("PyWinRT", "MIT", Symbol.Link), ("Pillow", "HPND", Symbol.Pictures), ("requests", "Apache-2.0", Symbol.Globe),
            ("keyring", "MIT", Symbol.Permissions), ("Шрифты", "SIL OFL 1.1", Symbol.Font), ("PyInstaller", "GPL с исключением", Symbol.Folder) })
        {
            var body = Form.Stack(8);
            body.Children.Add(new SymbolIcon(symbol) { HorizontalAlignment = HorizontalAlignment.Left });
            body.Children.Add(Form.Text(component, "BodyStrongTextBlockStyle"));
            body.Children.Add(Form.Text(license, "CaptionTextBlockStyle"));
            var card = Form.Card(body);
            card.Width = 124; card.Height = 124;
            componentGrid.Children.Add(card);
        }
        components.Children.Add(componentGrid);
        page.Add(components);
        var faq = Form.Section("Частые вопросы");
        foreach (var (q, a) in new[] {
            ("Где взять LocalToken для Times Gate?", "Откройте настройки Times Gate в приложении Divoom."),
            ("Как спарить Ditoo Pro?", "Откройте Bluetooth в параметрах Windows и выберите DitooPro-Audio."),
            ("Что выбрать для музыки?", "Медиасессия получает трек от Windows. Spotify Web API нужен для воспроизведения на другом устройстве."),
            ("Почему часы могут остановиться после выхода?", "Пользовательские кадры рисует приложение. Встроенный циферблат работает на самом устройстве."),
            ("Где лежит профиль интерфейса?", "%LOCALAPPDATA%\\DivoomHub.WinUI\\ui-settings.json") })
            faq.Children.Add(new Expander { Header = q, Content = Form.Text(a), HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Stretch });
        page.Add(faq);
        return page;
    }
}
