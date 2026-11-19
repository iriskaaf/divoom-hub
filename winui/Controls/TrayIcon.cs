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
            var item = new MenuFlyoutItem { Text = text, Icon = new SymbolIcon(symbol) };
            item.Click += (_, _) => action();
            return item;
        }
        menu.Items.Add(Item("Открыть Divoom Hub", Symbol.OpenPane, window.ShowWindow));
        menu.Items.Add(Item(window.Profile.ShowArtwork ? "Приостановить отслеживание музыки" : "Возобновить отслеживание музыки",
            window.Profile.ShowArtwork ? Symbol.Pause : Symbol.Play, () =>
            {
                window.Profile.ShowArtwork = !window.Profile.ShowArtwork;
                window.Save();
            }));
        foreach (var gate in window.Profile.Devices.Where(x => x.Kind == "gate"))
        {
            var device = new MenuFlyoutSubItem { Text = gate.Name, Icon = new SymbolIcon(Symbol.Clock) };
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
        AppWindow.Hide();
    }

    internal void Open(MenuFlyout menu, ElementTheme theme)
    {
        _root.RequestedTheme = theme;
        _root.Background = ClockPreview.Brush(theme == ElementTheme.Dark ? "#2C2C2C" : "#FAFAFA");
        var content = new MenuFlyoutPresenter { ItemsSource = menu.Items, MinWidth = 300, MaxWidth = 420 };
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
        int width = Math.Min(area.Width, (int)Math.Ceiling(360 * scale));
        int height = Math.Min(area.Height, (int)Math.Ceiling((16 + menu.Items.Sum(x => x is MenuFlyoutSeparator ? 12 : 40)) * scale));
        AppWindow.MoveAndResize(new Windows.Graphics.RectInt32(
            Math.Clamp(point.X - width, area.X, area.X + area.Width - width),
            Math.Clamp(point.Y - height, area.Y, area.Y + area.Height - height), width, height));
        AppWindow.Show();
        Activate();
        _open = true;
        DispatcherQueue.TryEnqueue(() => menu.Items.FirstOrDefault()?.Focus(FocusState.Programmatic));
    }

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern uint GetDpiForWindow(IntPtr hwnd);
}
