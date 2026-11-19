using Microsoft.UI.Xaml.Controls;
using System;
using System.IO;
using System.Linq;

namespace divoom_hub_winui3;

internal static class LocalFilePage
{
    // File selection lives inside the main window as well.
    public static void Open(MainWindow window, string title, string[] extensions, Action<string> use, Action back, bool saving = false)
    {
        var page = new PageSurface(title, back);
        string directory = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var path = new TextBox { Header = "Папка или полный путь к файлу" };
        var entries = new ListView { MaxHeight = 340, IsItemClickEnabled = true, SelectionMode = ListViewSelectionMode.None };
        var folderLine = Form.Text("");
        var confirm = Form.Button("Заменить существующий файл", null);
        confirm.Visibility = Microsoft.UI.Xaml.Visibility.Collapsed;
        string? overwrite = null;
        void Browse(string folder)
        {
            try
            {
                var dirs = Directory.EnumerateDirectories(folder).OrderBy(Path.GetFileName).Take(250);
                var files = Directory.EnumerateFiles(folder).Where(file => extensions.Contains(Path.GetExtension(file), StringComparer.OrdinalIgnoreCase))
                    .OrderBy(Path.GetFileName).Take(250);
                entries.ItemsSource = dirs.Concat(files).Select(file => new ListViewItem
                { Content = (Directory.Exists(file) ? "▸  " : "     ") + Path.GetFileName(file), Tag = file }).ToArray();
                directory = folder;
                folderLine.Text = folder;
                path.Text = folder;
                overwrite = null;
                confirm.Visibility = Microsoft.UI.Xaml.Visibility.Collapsed;
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException)
            { page.Message("Не удалось открыть папку.", InfoBarSeverity.Error); }
        }
        void Apply(string input)
        {
            try
            {
                string target = Path.GetFullPath(input.Trim().Trim('"'), directory);
                if (Directory.Exists(target)) { Browse(target); return; }
                if (!extensions.Contains(Path.GetExtension(target), StringComparer.OrdinalIgnoreCase) || (!saving && !File.Exists(target)))
                    throw new IOException();
                if (saving && File.Exists(target))
                {
                    overwrite = target;
                    confirm.Visibility = Microsoft.UI.Xaml.Visibility.Visible;
                    page.Message("Файл уже существует. Подтвердите замену.", InfoBarSeverity.Warning);
                    return;
                }
                use(target);
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException or ArgumentException or InvalidDataException or System.Text.Json.JsonException)
            { page.Message("Не удалось открыть или сохранить файл. Проверьте путь и формат.", InfoBarSeverity.Error); }
        }
        confirm.IsEnabled = true;
        confirm.Click += (_, _) =>
        {
            if (overwrite is null) return;
            try { use(overwrite); }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException or ArgumentException)
            { page.Message("Не удалось заменить файл.", InfoBarSeverity.Error); }
        };
        entries.ItemClick += (_, e) => { if (e.ClickedItem is ListViewItem { Tag: string target }) { if (Directory.Exists(target)) Browse(target); else path.Text = target; } };
        var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        actions.Children.Add(Form.Button("На уровень выше", () => { if (Directory.GetParent(directory) is DirectoryInfo parent) Browse(parent.FullName); }));
        actions.Children.Add(Form.Button(saving ? "Сохранить" : "Открыть", () => Apply(path.Text), true));
        page.Add(path);
        page.Add(actions);
        page.Add(confirm);
        page.Add(folderLine);
        page.Add(entries);
        Browse(directory);
        window.Show(page);
    }
}
