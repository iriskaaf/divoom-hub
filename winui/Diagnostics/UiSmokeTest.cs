using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Automation.Provider;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Windows.Graphics.Imaging;
using Windows.Storage;

namespace divoom_hub_winui3;

internal static class UiSmokeTest
{
    internal static async void Run(string report)
    {
        MainWindow? window = null;
        try
        {
            File.WriteAllText(report, "Running UI checks");
            window = new MainWindow(new HubProfile { OnboardingCompleted = true, DitooEnabled = true,
                TimesgateEnabled = true, DeveloperMode = true });
            window.AppWindow.Move(new Windows.Graphics.PointInt32(-4400, -4400));
            window.Activate();
            var gate = window.Profile.Devices.First(x => x.Kind == "gate");
            var ditoo = window.Profile.Devices.First(x => x.Kind == "ditoo");
            window.State(ditoo).Online = true;
            window.RefreshDeviceMenu();
            await Check((FrameworkElement)window.Content);
            var nav = Descendants((FrameworkElement)window.Content).OfType<NavigationView>().Single();
            if (nav.MenuItems[2] is not NavigationViewItem first || !Equals(first.Tag, ditoo.Id))
                throw new InvalidOperationException("Online devices must come first");
            if (Edition.Test && LegacyImport.Available && !LegacyImport.Read(window.Catalog).OnboardingCompleted)
                throw new InvalidOperationException("Legacy settings failed to load for TEST");
            File.WriteAllText(report, "Checking native tray menu");
            var trayHost = new TrayMenuHost();
            File.WriteAllText(report, "Created native tray anchor");
            try
            {
                var menu = TrayIcon.CreateMenu(window, () => { });
                trayHost.Open(menu, ElementTheme.Dark);
                if (Environment.GetEnvironmentVariable("DIVOOM_TRAY_PREVIEW") == "1") await Task.Delay(30000);
                File.WriteAllText(report, "Opening native tray menu");
                await Task.Delay(300);
                if (!trayHost.AppWindow.IsVisible) throw new InvalidOperationException("Native tray menu did not open");
                var anchor = (FrameworkElement)trayHost.Content;
                File.WriteAllText(report, $"Tray loaded={anchor.IsLoaded}, size={anchor.ActualWidth}x{anchor.ActualHeight}, window={trayHost.AppWindow.Size}, root={anchor.XamlRoot?.Size}");
                if (!anchor.IsLoaded || anchor.ActualWidth <= 0 || !Descendants(anchor).OfType<MenuFlyoutItem>().Any())
                    throw new InvalidOperationException("Native menu items did not load");
                trayHost.Dismiss();
                await Task.Delay(150);
                if (trayHost.AppWindow.IsVisible) throw new InvalidOperationException("Tray anchor remained visible");
            }
            finally { trayHost.Close(); }
            foreach (string theme in new[] { "dark", "light" })
            {
                window.Profile.UiTheme = theme;
                window.ApplyTheme();
                foreach (string route in new[] { "home", "gate", "ditoo", "settings", "about" })
                {
                    window.Navigate(route);
                    await Check((FrameworkElement)window.Content, route == "gate" || route == "settings" ? Path.ChangeExtension(report, $"{route}-{theme}.png") : null);
                }
            }
            window.Show(DevicePages.Connection(window, window.Profile.Devices.First(x => x.Kind == "gate"), () => { }));
            await Check((FrameworkElement)window.Content);
            window.Show(DevicePages.Connection(window, window.Profile.Devices.First(x => x.Kind == "ditoo"), () => { }));
            await Check((FrameworkElement)window.Content);
            gate.Settings.TgMode = "gifs_clock";
            window.Navigate("gate");
            await Check((FrameworkElement)window.Content);
            foreach (var face in window.Profile.TgThemes)
            {
                GatePages.Edit(window, face);
                await Check((FrameworkElement)window.Content);
            }
            GatePages.Edit(window, new ClockFace(), isNew: true);
            await Check((FrameworkElement)window.Content);
            window.StartSetup(true);
            await Check((FrameworkElement)window.Content);
            window.FinishSetup(true);
            window.StartSetup(false);
            await Check((FrameworkElement)window.Content, Path.ChangeExtension(report, "welcome.png"));
            FrameworkElement root = (FrameworkElement)window.Content;
            await Click(root, "Оставить текущие устройства");
            if (!Descendants(root).OfType<TextBlock>().Any(x => x.Text == "Медиасессия Windows"))
                throw new InvalidOperationException("Music source page did not appear");
            await Check(root, Path.ChangeExtension(report, "music.png"));
            await Click(root, "Продолжить");
            if (window.Profile.Devices.Count != 2 || !window.Profile.OnboardingCompleted)
                throw new InvalidOperationException("Setup unexpectedly removed devices");
            await CheckColorDialog(window, report);
            string zip = Path.ChangeExtension(report, ".zip");
            try
            {
                ClockFace swiss = window.Catalog.Faces.First(face => face.Style == "swiss");
                FacePacks.Export(swiss, zip);
                ClockFace restored = FacePacks.Import(zip, window.Catalog);
                if (restored.Name != swiss.Name || !restored.Palette.OrderBy(x => x.Key).SequenceEqual(swiss.Palette.OrderBy(x => x.Key)))
                    throw new InvalidDataException("ZIP round trip changed the face");
            }
            finally { if (File.Exists(zip)) File.Delete(zip); }
            var backend = new PythonBackend();
            var ready = new TaskCompletionSource();
            backend.Event += (name, _, _) => { if (name == "ready") ready.TrySetResult(); };
            backend.Start();
            try
            {
                await ready.Task.WaitAsync(TimeSpan.FromSeconds(15));
                await backend.CallAsync("configure_all", new
                {
                    music = new { show_artwork = false },
                    devices = new[] { new { id = "smoke", kind = "gate", settings = new { tg_mode = "clock" } } },
                });
                var result = await backend.CallAsync("preview", new { device = "smoke" });
                if (result.GetArrayLength() != 5 || await LiveState.DecodeAsync(result[2]) is not BitmapImage)
                    throw new InvalidDataException("Expected five previews from Python");
            }
            finally { await backend.StopAsync(); }
            File.WriteAllText(report, "PASS: both themes and pages, wizard, renderers, ZIP round trip, Python handshake, settings and PNG preview over IPC");
        }
        catch (Exception e)
        {
            File.WriteAllText(report, e.ToString());
            Environment.ExitCode = 1;
        }
        finally
        {
            window?.Close();
            Application.Current.Exit();
        }
    }

    private static async Task CheckColorDialog(MainWindow window, string report)
    {
        string saved = "#FF2BD6";
        var page = new PageSurface("Подсветка");
        page.Add(GatePages.ColorEditor("Цвет подсветки", saved, value => saved = value));
        window.Show(page);
        var root = (FrameworkElement)window.Content;
        await Check(root);
        var button = Descendants(root).OfType<Button>().Single(x => AutomationProperties.GetName(x) == "Цвет подсветки");
        async Task<ContentDialog> Open()
        {
            var peer = new ButtonAutomationPeer(button);
            ((IInvokeProvider)peer.GetPattern(PatternInterface.Invoke)).Invoke();
            await Task.Delay(350);
            return VisualTreeHelper.GetOpenPopupsForXamlRoot(root.XamlRoot)
                .SelectMany(p => Descendants(p.Child).Prepend(p.Child)).Concat(Descendants(root)).OfType<ContentDialog>().Single();
        }
        var dialog = await Open();
        var picker = Descendants(dialog).OfType<ColorPicker>().Single();
        picker.Color = Windows.UI.Color.FromArgb(255, 12, 160, 80);
        await Check(dialog, Path.ChangeExtension(report, "color.png"));
        await Click(dialog, "Отмена");
        if (saved != "#FF2BD6") throw new InvalidOperationException("Cancel changed the saved color");
        dialog = await Open();
        Descendants(dialog).OfType<ColorPicker>().Single().Color = Windows.UI.Color.FromArgb(255, 12, 160, 80);
        await Click(dialog, "Готово");
        if (!saved.Equals("#0CA050", StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("Color was not applied");
    }

    private static IEnumerable<DependencyObject> Descendants(DependencyObject node)
    {
        for (int i = 0; i < VisualTreeHelper.GetChildrenCount(node); i++)
        {
            var child = VisualTreeHelper.GetChild(node, i);
            yield return child;
            foreach (var nested in Descendants(child)) yield return nested;
        }
    }

    private static async Task Click(FrameworkElement root, string name)
    {
        var button = Descendants(root).OfType<Button>().Single(x => x.Content as string == name && x.IsEnabled);
        var peer = new ButtonAutomationPeer(button);
        ((IInvokeProvider)peer.GetPattern(PatternInterface.Invoke)).Invoke();
        if (root is ContentDialog) await Task.Delay(350);
        else await Check(root);
    }

    private static async Task Check(FrameworkElement root, string? png = null)
    {
        await Task.Delay(550);
        root.UpdateLayout();
        var image = new RenderTargetBitmap();
        await image.RenderAsync(root, 600, 440);
        if (image.PixelWidth == 0 || image.PixelHeight == 0)
            throw new InvalidOperationException("No pixels rendered");
        if (png is not null)
        {
            var folder = await StorageFolder.GetFolderFromPathAsync(Path.GetDirectoryName(png)!);
            var file = await folder.CreateFileAsync(Path.GetFileName(png), CreationCollisionOption.ReplaceExisting);
            using var stream = await file.OpenAsync(FileAccessMode.ReadWrite);
            var encoder = await BitmapEncoder.CreateAsync(BitmapEncoder.PngEncoderId, stream);
            var buffer = await image.GetPixelsAsync();
            using var bitmap = SoftwareBitmap.CreateCopyFromBuffer(buffer, BitmapPixelFormat.Bgra8,
                image.PixelWidth, image.PixelHeight, BitmapAlphaMode.Premultiplied);
            encoder.SetSoftwareBitmap(bitmap);
            await encoder.FlushAsync();
        }
    }
}
