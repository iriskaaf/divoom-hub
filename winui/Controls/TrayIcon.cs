using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using System;
using System.Drawing;
using System.IO;
using System.Linq;
using Forms = System.Windows.Forms;

namespace divoom_hub_winui3;

internal sealed class TrayIcon : IDisposable
{
    private readonly MainWindow _window;
    private readonly Forms.NotifyIcon _icon;
    private readonly Icon _image;
    private readonly TrayMenuHost _host = new();
    private bool _exiting;
    private bool _disposed;

    public TrayIcon(MainWindow window)
    {
        _window = window;
        _image = new Icon(Path.Combine(AppContext.BaseDirectory, "Assets", "icon.ico"));
        _icon = new Forms.NotifyIcon { Icon = _image, Text = Edition.Test ? "Divoom Hub · TEST" : "Divoom Hub", Visible = true };
        _icon.MouseUp += (_, e) => window.DispatcherQueue.TryEnqueue(() =>
        {
            if (_disposed) return;
            if (e.Button == Forms.MouseButtons.Left) window.ShowWindow();
            else if (e.Button == Forms.MouseButtons.Right)
                _host.Open(CreateMenu(window, async () => { _exiting = true; await window.QuitAsync(); }),
                    window.TrayDark ? ElementTheme.Dark : ElementTheme.Light);
        });
        window.AppWindow.Closing += HideOnClose;
        window.Closed += (_, _) => Dispose();
    }

    internal static MenuFlyout CreateMenu(MainWindow window, Action quit)
    {
        var menu = new MenuFlyout();
        MenuFlyoutItem Item(string text, Symbol symbol, Action action)
        {
            var item = new MenuFlyoutItem { Text = text, Icon = new SymbolIcon(symbol), MinHeight = 32, Padding = new Thickness(12, 6, 12, 6), FontSize = 14 };
            item.Click += (_, _) => action();
            return item;
        }
        foreach (var device in window.Profile.Devices)
        {
            string status = window.State(device).Online ? device.Kind == "gate" ? device.Face.Name : "Подключено" : "Отключено";
            var item = Item($"{device.Name}: {status}", device.Kind == "gate" ? Symbol.Clock : Symbol.Audio, () => { });
            item.IsEnabled = false;
            menu.Items.Add(item);
        }
        var music = Item("Музыка: " + window.Live.Music, Symbol.Audio, () => { });
        music.IsEnabled = false;
        menu.Items.Add(music);
        menu.Items.Add(new MenuFlyoutSeparator());
        menu.Items.Add(Item("Показать", Symbol.Home, window.ShowWindow));
        menu.Items.Add(Item(window.Profile.ShowArtwork ? "Пауза интеграции" : "Возобновить интеграцию",
            window.Profile.ShowArtwork ? Symbol.Pause : Symbol.Play, () =>
            {
                window.Profile.ShowArtwork = !window.Profile.ShowArtwork;
                window.Save();
            }));
        foreach (var gate in window.Profile.Devices.Where(x => x.Kind == "gate"))
        {
            var device = new MenuFlyoutSubItem { Text = gate.Name, Icon = new SymbolIcon(Symbol.Clock), MinHeight = 32, Padding = new Thickness(12, 6, 12, 6), FontSize = 14 };
            if (window.Profile.Devices.Count(x => x.Kind == "gate") == 1)
            {
                menu.Items.Add(Item("Следующий циферблат", Symbol.Forward, () => window.StepFace(gate, 1)));
                menu.Items.Add(Item("Встроенный циферблат Times Gate", Symbol.Clock, () => window.SetGateModeFromTray(gate, "device")));
                continue;
            }
            device.Items.Add(Item("Предыдущий циферблат", Symbol.Previous, () => window.StepFace(gate, -1)));
            device.Items.Add(Item("Следующий циферблат", Symbol.Next, () => window.StepFace(gate, 1)));
            device.Items.Add(Item("Встроенный циферблат", Symbol.Clock, () => window.SetGateModeFromTray(gate, "device")));
            menu.Items.Add(device);
        }
        menu.Items.Add(new MenuFlyoutSeparator());
        menu.Items.Add(Item("Выход", Symbol.Cancel, quit));
        return menu;
    }

    private void HideOnClose(AppWindow sender, AppWindowClosingEventArgs args)
    {
        if (_exiting) return;
        args.Cancel = true;
        _window.HideWindow();
    }

    internal void Hide() => _icon.Visible = false;

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _window.AppWindow.Closing -= HideOnClose;
        _icon.Dispose();
        _image.Dispose();
        _host.Close();
    }
}

// MenuFlyoutPresenter supplies WinUI styling and keyboard navigation without a visible main window.
internal sealed class TrayMenuHost : Window
{
    private readonly Grid _root = new();
    private bool _open;
    private bool _hadFocus;
    private readonly Microsoft.UI.Dispatching.DispatcherQueueTimer _focusTimer;

    internal TrayMenuHost()
    {
        Content = _root;
        AppWindow.IsShownInSwitchers = false;
        var presenter = OverlappedPresenter.Create();
        presenter.IsResizable = false;
        presenter.IsMaximizable = false;
        presenter.IsMinimizable = false;
        presenter.IsAlwaysOnTop = true;
        presenter.SetBorderAndTitleBar(false, false);
        AppWindow.SetPresenter(presenter);
        _focusTimer = DispatcherQueue.CreateTimer();
        _focusTimer.Interval = TimeSpan.FromMilliseconds(150);
        _focusTimer.Tick += (_, _) =>
        {
            var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
            var foreground = GetForegroundWindow();
            bool ownsFocus = foreground == hwnd || GetAncestor(foreground, 3) == hwnd;
            if (ownsFocus) _hadFocus = true;
            var mouse = Forms.Cursor.Position;
            var bounds = AppWindow.Position;
            var size = AppWindow.Size;
            bool outside = mouse.X < bounds.X || mouse.Y < bounds.Y || mouse.X >= bounds.X + size.Width || mouse.Y >= bounds.Y + size.Height;
            bool clicked = (GetAsyncKeyState(1) & 0x8000) != 0 || (GetAsyncKeyState(2) & 0x8000) != 0;
            if (_open && !ownsFocus && ((_hadFocus) || (outside && clicked))) Dismiss();
        };
        Closed += (_, _) => _focusTimer.Stop();
        Activated += (_, e) =>
        {
            if (e.WindowActivationState == WindowActivationState.Deactivated && _open)
                DispatcherQueue.TryEnqueue(Dismiss);
        };
        _root.KeyDown += (_, e) =>
        {
            if (e.Key == Windows.System.VirtualKey.Escape) { Dismiss(); e.Handled = true; }
        };
    }

    internal void Dismiss()
    {
        _open = false;
        _focusTimer.Stop();
        AppWindow.Hide();
    }

    internal void Open(MenuFlyout menu, ElementTheme theme)
    {
        _root.RequestedTheme = theme;
        _root.Background = ClockPreview.Brush(theme == ElementTheme.Dark ? "#2C2C2C" : "#FAFAFA");
        var content = new MenuFlyoutPresenter { ItemsSource = menu.Items, MinWidth = 300, MaxWidth = 420,
            BorderThickness = new Thickness(0), Padding = new Thickness(4), CornerRadius = new CornerRadius(8) };
        void DismissOnClick(System.Collections.Generic.IEnumerable<MenuFlyoutItemBase> items)
        {
            foreach (var item in items)
            {
                if (item is MenuFlyoutItem action) action.Click += (_, _) => Dismiss();
                if (item is MenuFlyoutSubItem sub) DismissOnClick(sub.Items);
            }
        }
        DismissOnClick(menu.Items);
        _root.Children.Clear();
        _root.Children.Add(content);
        var point = Forms.Cursor.Position;
        var area = DisplayArea.GetFromPoint(new Windows.Graphics.PointInt32(point.X, point.Y), DisplayAreaFallback.Nearest).WorkArea;
        AppWindow.Move(new Windows.Graphics.PointInt32(point.X, point.Y));
        double scale = GetDpiForWindow(WinRT.Interop.WindowNative.GetWindowHandle(this)) / 96d;
        int width = Math.Min(area.Width, (int)Math.Ceiling(320 * scale));
        int height = Math.Min(area.Height, (int)Math.Ceiling((14 + menu.Items.Sum(x => x is MenuFlyoutSeparator ? 12 : 32)) * scale));
        AppWindow.MoveAndResize(new Windows.Graphics.RectInt32(
            Math.Clamp(point.X - width, area.X, area.X + area.Width - width),
            Math.Clamp(point.Y - height, area.Y, area.Y + area.Height - height), width, height));
        AppWindow.Show();
        Activate();
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        int dark = theme == ElementTheme.Dark ? 1 : 0;
        int corner = 2;
        int border = theme == ElementTheme.Dark ? 0x00424242 : 0x00D0D0D0;
        DwmSetWindowAttribute(hwnd, 20, ref dark, sizeof(int));
        DwmSetWindowAttribute(hwnd, 33, ref corner, sizeof(int));
        DwmSetWindowAttribute(hwnd, 34, ref border, sizeof(int));
        SetForegroundWindow(hwnd);
        _hadFocus = GetForegroundWindow() == hwnd;
        _open = true;
        _focusTimer.Start();
        DispatcherQueue.TryEnqueue(() => menu.Items.FirstOrDefault(x => x.IsEnabled && x is MenuFlyoutItem)?.Focus(FocusState.Programmatic));
    }

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern uint GetDpiForWindow(IntPtr hwnd);
    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hwnd);
    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();
    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern short GetAsyncKeyState(int key);
    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern IntPtr GetAncestor(IntPtr hwnd, uint flags);
    [System.Runtime.InteropServices.DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, uint attribute, ref int value, int size);
}

