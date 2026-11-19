using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml;
using System;
using System.Net;
using System.Net.Sockets;
using System.Linq;

namespace divoom_hub_winui3;

internal static class DevicePages
{
    public static PageSurface Connection(MainWindow window, DeviceEntry device, Action back)
    {
        bool gate = device.Kind == "gate";
        var p = device.Settings;
        var state = window.State(device);
        var page = new PageSurface(device.Name, back);
        page.ShowStatus(window, state);
        var name = new TextBox { Text = device.Name, MaxLength = 40, MinWidth = 160 };
        page.Add(Form.Row("Название", "Имя в боковом меню", name, Form.Button("Переименовать", () =>
        {
            string candidate = name.Text.Trim();
            if (candidate.Length == 0) { page.Message("Введите название.", InfoBarSeverity.Warning); return; }
            string previous = device.Name;
            device.Name = candidate;
            if (window.Save()) { window.RefreshDeviceMenu(); page.SetTitle(device.Name); }
            else device.Name = previous;
        })));
        var status = Form.Text(state.Status);
        page.Observe(window, () => status.Text = state.Status);
        page.Add(Form.Row("Состояние", "", status));
        page.Add(ConnectionFields(window, device.Kind, p.DitooAddress, p.TgIp, p.TgToken, p.TgHardware,
            (address, ip, token, port, mac, hardware) =>
        {
            if (gate && !window.StoreLocalToken(device, token, page)) return;
            p.DitooAddress = address;
            p.DitooPort = port;
            p.TgIp = ip;
            p.TgToken = token;
            p.TgMac = mac;
            p.TgHardware = hardware;
            if (!window.Save()) return;
            page.Message("Подключение подтверждено, параметры сохранены.", InfoBarSeverity.Success);
            _ = window.RunCommand(gate ? "reconnect_gate" : "connect_ditoo", page, device: device);
        }, "Подключить", device));
        if (!gate)
            page.Add(Form.Button("Отключить Ditoo", () => _ = window.RunCommand("disconnect_ditoo", page, device: device)));
        page.Add(Form.Button("Удалить устройство", () =>
        {
            var confirm = new PageSurface("Удалить устройство", () => window.Show(Connection(window, device, back)));
            confirm.Add(Form.Text($"Удалить «{device.Name}» из Divoom Hub?"));
            confirm.Add(Form.Button("Удалить", () => window.RemoveDevice(device)));
            window.Show(confirm);
        }));
        return page;
    }

    public static StackPanel ConnectionFields(MainWindow window, string device, string address, string ip, string token, int hardware,
        Action<string, string, string, int, string, int> save, string buttonText, DeviceEntry? editing = null)
    {
        bool gate = device == "gate";
        var panel = Form.Stack(12);
        panel.Children.Add(Form.Text(gate
            ? "Подключите Times Gate к Wi-Fi. IP найдите в роутере, LocalToken — в настройках устройства в приложении Divoom."
            : "Спарьте DitooPro-Audio в параметрах Bluetooth Windows. Введите Bluetooth-адрес устройства."));
        var addressBox = new TextBox { Header = gate ? "IP-адрес" : "Bluetooth-адрес", Text = gate ? ip : address,
            PlaceholderText = gate ? "192.168.1.50" : "AA:BB:CC:DD:EE:FF", MaxLength = 40 };
        var tokenBox = new PasswordBox { Header = "LocalToken", Password = token, MaxLength = 32,
            PlaceholderText = "Числовой код из приложения Divoom" };
        addressBox.Header = null;
        addressBox.MinWidth = 150;
        tokenBox.Header = null;
        tokenBox.MinWidth = 150;
        var status = new InfoBar { IsClosable = true };
        void Say(string text, InfoBarSeverity severity = InfoBarSeverity.Informational)
        {
            status.Severity = severity;
            status.Message = text;
            status.IsOpen = true;
        }
        string mac = gate && editing is not null ? editing.Settings.TgMac : "";
        string macIp = ip;
        var devices = new ComboBox { Header = "Найденные устройства", Visibility = Visibility.Collapsed };
        devices.SelectionChanged += (_, _) =>
        {
            if (devices.SelectedItem is ComboBoxItem { Tag: ValueTuple<string, string> selected })
            {
                (macIp, mac) = selected;
                addressBox.Text = macIp;
            }
        };
        var showAll = new ToggleSwitch { Header = "Показывать все Bluetooth-устройства" };
        if (!gate) panel.Children.Add(showAll);
        var scan = new Button { Content = gate ? "Найти в сети" : "Найти спаренные устройства" };
        scan.Click += async (_, _) =>
        {
            scan.IsEnabled = false;
            try
            {
                var result = await window.CommandAsync(gate ? "scan_gate" : "scan_ditoo", new { all = showAll.IsOn });
                devices.Items.Clear();
                foreach (var item in result.EnumerateArray())
                {
                    string found = item.GetProperty(gate ? "ip" : "address").GetString() ?? "";
                    if (found.Length == 0) continue;
                    string label = item.GetProperty("name").GetString() ?? "";
                    string foundMac = gate ? item.GetProperty("mac").GetString() ?? "" : "";
                    devices.Items.Add(new ComboBoxItem { Content = $"{label} · {found}", Tag = (found, foundMac) });
                }
                devices.Visibility = devices.Items.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
                if (devices.Items.Count == 1) devices.SelectedIndex = 0;
                Say(devices.Items.Count > 0 ? "Выберите устройство из списка." : "Устройства не найдены.");
            }
            catch (Exception e) when (MainWindow.IsBackendError(e))
            { Say(e is BackendException ? e.Message : "Поиск недоступен.", InfoBarSeverity.Warning); }
            finally { scan.IsEnabled = true; }
        };
        panel.Children.Add(Form.Row(gate ? "IP-адрес" : "Bluetooth-адрес",
            gate ? "«Найти» ищет устройства в вашей сети" : "Спаренное в Windows устройство", addressBox, scan));
        panel.Children.Add(devices);
        if (gate)
        {
            panel.Children.Add(Form.Row("LocalToken", "Приложение Divoom → настройки устройства", tokenBox));
            panel.Children.Add(new Expander { Header = "Дополнительно", Content =
                Form.Combo("Ревизия Times Gate", hardware.ToString(), [("400", "400 · порт 80"), ("402", "402 · порт 9000")],
                    value => hardware = int.Parse(value)) });
        }
        var connect = new Button { Content = buttonText, Style = (Style)Application.Current.Resources["AccentButtonStyle"] };
        connect.Click += async (_, _) =>
        {
            string input = addressBox.Text.Trim();
            string code = tokenBox.Password.Trim();
            bool valid = gate
                ? IPAddress.TryParse(input, out var parsed) && parsed.AddressFamily == AddressFamily.InterNetwork
                    && input.Split('.').Length == 4 && code.Length > 0 && Array.TrueForAll(code.ToCharArray(), char.IsAsciiDigit)
                : System.Text.RegularExpressions.Regex.IsMatch(input, @"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$");
            if (!valid)
            {
                Say(gate ? "Введите адрес IPv4 и числовой LocalToken." : "Введите адрес в формате AA:BB:CC:DD:EE:FF.", InfoBarSeverity.Error);
                return;
            }
            if (window.Profile.Devices.Any(x => x != editing && x.Kind == device &&
                string.Equals(x.Address, input, StringComparison.OrdinalIgnoreCase)))
            { Say("Это устройство уже добавлено.", InfoBarSeverity.Warning); return; }
            connect.IsEnabled = false;
            Say("Проверяем связь с устройством…");
            try
            {
                int port = 0;
                if (gate) await window.CommandAsync("probe_gate", new { ip = input, token = code, hardware });
                else port = (await window.CommandAsync("probe_ditoo", new { address = input })).GetInt32();
                if (panel.IsLoaded)
                    save(gate ? address : input.ToUpperInvariant(), gate ? input : ip, gate ? code : token, port, macIp == input ? mac : "", hardware);
            }
            catch (Exception e) when (MainWindow.IsBackendError(e))
            { Say(e is BackendException ? e.Message : "Устройство не ответило.", InfoBarSeverity.Error); }
            finally { connect.IsEnabled = true; }
        };
        panel.Children.Add(connect);
        panel.Children.Add(status);
        return panel;
    }

    public static PageSurface Ditoo(MainWindow window, DeviceEntry device)
    {
        var p = device.Settings;
        var live = window.State(device);
        var page = new PageSurface(device.Name);
        page.ShowStatus(window, live);
        var connection = Form.Section("Подключение");
        var status = Form.Text(live.Status);
        page.Observe(window, () => status.Text = live.Status);
        connection.Children.Add(status);
        connection.Children.Add(Form.Button("Настроить подключение", () => window.Show(Connection(window, device, () => window.Navigate(device.Id)))));
        connection.Children.Add(Form.Toggle("Подключаться автоматически", p.AutoReconnect, value => { p.AutoReconnect = value; window.Save(); }));
        page.Add(Form.Card(connection));

        var screen = Form.Section("Экран");
        screen.Children.Add(Form.Slider("Яркость экрана", p.Brightness, 0, 100, value => { p.Brightness = (int)value; window.SaveSoon(); }));
        var delay = new NumberBox { Header = "Задержка, с", Value = p.IdleDelayS, Minimum = 0, Maximum = 600, SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Inline };
        delay.ValueChanged += (_, e) => { if (double.IsFinite(e.NewValue)) { p.IdleDelayS = (int)e.NewValue; window.Save(); } };
        delay.Visibility = p.IdleMode == "keep" ? Microsoft.UI.Xaml.Visibility.Collapsed : Microsoft.UI.Xaml.Visibility.Visible;
        screen.Children.Add(Form.Combo("Когда музыка не играет", p.IdleMode, window.Catalog.Idle, value =>
        {
            p.IdleMode = value;
            delay.Visibility = value == "keep" ? Microsoft.UI.Xaml.Visibility.Collapsed : Microsoft.UI.Xaml.Visibility.Visible;
            window.Save();
        }));
        screen.Children.Add(delay);
        page.Add(Form.Card(screen));

        var artwork = Form.Stack();
        var contrast = Form.Slider("Контраст", p.Contrast * 100, 0, 200, value => { p.Contrast = value / 100; window.SaveSoon(); });
        var saturation = Form.Slider("Насыщенность", p.Saturation * 100, 0, 200, value => { p.Saturation = value / 100; window.SaveSoon(); });
        var brightness = Form.Slider("Яркость картинки", p.ArtBrightness * 100, 0, 200, value => { p.ArtBrightness = value / 100; window.SaveSoon(); });
        artwork.Children.Add(contrast);
        artwork.Children.Add(saturation);
        artwork.Children.Add(brightness);
        artwork.Children.Add(Form.Button("Сбросить", () => { contrast.Value = 110; saturation.Value = 115; brightness.Value = 100; }));
        page.Add(new Expander { Header = "Обработка обложки", Content = artwork, HorizontalAlignment = Microsoft.UI.Xaml.HorizontalAlignment.Stretch,
            HorizontalContentAlignment = Microsoft.UI.Xaml.HorizontalAlignment.Stretch });
        if (p.DeveloperMode)
        {
            var tools = Form.Stack();
            foreach (var (label, command) in new[] { ("Проверить режим простоя", "idle"), ("Тестовая картинка", "test"),
                ("Очистить экран", "clear"), ("Диагностика палитры", "diagnostic"), ("Подсветка клавиш вкл./выкл.", "TOGGLE"),
                ("Предыдущий эффект", "PREV"), ("Следующий эффект", "NEXT") })
                tools.Children.Add(Form.Button(label, () => _ = window.RunCommand("ditoo_" + command, page)));
            tools.Children.Add(Form.Button("Показать файл", () =>
                LocalFilePage.Open(window, "Картинка для Ditoo", FacePacks.MediaExtensions, path =>
                {
                    window.Navigate(device.Id);
                    _ = window.RunCommand("ditoo_file", window.ActivePage!, new { path });
                }, () => window.Navigate(device.Id))));
            page.Observe(window, () =>
            {
                foreach (var button in tools.Children.OfType<Button>()) button.IsEnabled = live.Online;
            });
            page.Add(new Expander { Header = "Ручные тесты", Content = tools, HorizontalAlignment = HorizontalAlignment.Stretch });
        }
        return page;
    }
}
