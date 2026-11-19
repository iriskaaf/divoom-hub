using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using System;
using System.Linq;
using System.Collections.Generic;
using Microsoft.UI.Xaml.Controls.Primitives;

namespace divoom_hub_winui3;

internal static class GatePages
{
    private static readonly (string, string)[] Modes =
    [
        ("clock", "Часы на пяти экранах"), ("gifs_clock", "Картинки по бокам, часы в центре"),
        ("device", "Встроенный циферблат"), ("off", "Не управлять экранами")
    ];

    public static PageSurface Create(MainWindow window)
    {
        var device = window.CurrentDevice!;
        var p = device.Settings;
        string route = device.Id;
        var live = window.State(device);
        var page = new PageSurface(device.Name);
        page.ShowStatus(window, live);
        var preview = Form.Stack(16);
        var screens = new ContentControl { HorizontalContentAlignment = HorizontalAlignment.Stretch };
        preview.Children.Add(screens);
        var gallery = Form.Stack();
        preview.Children.Add(gallery);
        page.Add(Form.Card(preview));
        object? lastFrames = null;
        page.Observe(window, () =>
        {
            if (live.Frames.Any(frame => frame is not null) && p.TgMode is ("clock" or "gifs_clock") && !ReferenceEquals(lastFrames, live.Frames))
            {
                lastFrames = live.Frames;
                ShowScreens(ClockPreview.FromFrames(live.Frames));
            }
        });

        void ShowScreens(UIElement frames)
        {
            if (p.TgMode != "gifs_clock") { screens.Content = frames; return; }
            var layer = new Grid { Width = 540, Height = 104 };
            layer.Children.Add(frames);
            for (int slot = 0; slot < 4; slot++)
            {
                int index = slot;
                int display = slot < 2 ? slot : slot + 1;
                bool filled = !string.IsNullOrWhiteSpace(p.TgSideMedia[index]);
                var edit = Form.Button("", () => LocalFilePage.Open(window, "Картинка для экрана", FacePacks.MediaExtensions,
                    path => { p.TgSideMedia[index] = path; if (window.Save()) window.Navigate(route); }, () => window.Navigate(route)));
                edit.Content = new FontIcon { Glyph = filled ? "\uE70F" : "\uE710", FontSize = 16 };
                edit.Width = edit.Height = 32;
                edit.Padding = new Thickness(4);
                edit.HorizontalAlignment = HorizontalAlignment.Left;
                edit.VerticalAlignment = filled ? VerticalAlignment.Top : VerticalAlignment.Center;
                edit.Margin = new Thickness(display * 109 + (filled ? 68 : 36), filled ? 4 : 0, 0, 0);
                Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(edit, $"Изменить экран {display + 1}");
                var menu = new MenuFlyout();
                var clear = new MenuFlyoutItem { Text = "Очистить экран", IsEnabled = filled };
                clear.Click += (_, _) => { p.TgSideMedia[index] = ""; window.Save(); window.Navigate(route); };
                menu.Items.Add(clear);
                edit.ContextFlyout = menu;
                layer.Children.Add(edit);
            }
            screens.Content = new Viewbox { Child = layer, StretchDirection = StretchDirection.DownOnly,
                HorizontalAlignment = HorizontalAlignment.Left };
        }

        var screenSettings = Form.Section("Экраны");
        var screenOptions = Form.Stack();
        (string, string)[]? lastBuiltins = null;
        var media = Form.Section("Картинки на боковых экранах");
        var connection = Form.Button("Настроить подключение", () => window.Show(
            DevicePages.Connection(window, device, () => window.Navigate(route))));
        var music = Form.Section("Музыка");
        var centerCover = Form.Toggle("Обложка вместо двоеточия", p.TgCenterCover, value => { p.TgCenterCover = value; window.Save(); });
        var faceColor = Form.Toggle("Циферблат под цвет обложки", p.TgFaceFollowCover, value => { p.TgFaceFollowCover = value; window.Save(); });
        var lightColor = Form.Toggle("Подсветка под цвет обложки", p.TgLightFollowCover, value =>
        { p.TgLightFollowCover = value; window.Save(); },
            "Если выбранный эффект не принимает цвет, во время трека используется совместимый эффект.");
        music.Children.Add(centerCover);
        music.Children.Add(lightColor);
        music.Children.Add(faceColor);
        var musicCard = Form.Card(music);

        bool IsCustomClock() => p.TgMode is "clock" or "gifs_clock";
        void Render()
        {
            ShowScreens(ClockPreview.Create(window.CurrentFace, p.TgMode, p.Tg24h, p.TgSideMedia));
            centerCover.Visibility = p.TgMode == "clock" ? Visibility.Visible : Visibility.Collapsed;
            faceColor.Visibility = IsCustomClock() && window.CurrentFace.Style != "custom" ? Visibility.Visible : Visibility.Collapsed;
            media.Visibility = p.TgMode == "gifs_clock" ? Visibility.Visible : Visibility.Collapsed;
            gallery.Visibility = IsCustomClock() ? Visibility.Visible : Visibility.Collapsed;
            screenOptions.Children.Clear();
            if (IsCustomClock())
            {
                screenOptions.Children.Add(Form.Toggle("24-часовой формат", p.Tg24h, value =>
                { p.Tg24h = value; window.Save(); screens.Content = ClockPreview.Create(window.CurrentFace, p.TgMode, value, p.TgSideMedia); }));
                screenOptions.Children.Add(Form.Toggle("Мигающее двоеточие", p.TgBlinkColon, value => { p.TgBlinkColon = value; window.Save(); }));
            }
            else if (p.TgMode == "device")
                screenOptions.Children.Add(Form.Combo("Циферблат устройства", p.TgDeviceFace.ToString(), window.Live.Builtins ?? window.Catalog.Builtin,
                    value => { p.TgDeviceFace = int.Parse(value); window.Save(); }));
        }

        page.Observe(window, () =>
        {
            if (p.TgMode != "device") return;
            if (window.Live.Builtins is null) _ = window.LoadBuiltinsAsync();
            else if (!ReferenceEquals(lastBuiltins, window.Live.Builtins))
            {
                lastBuiltins = window.Live.Builtins;
                Render();
            }
        });

        var galleryHead = new Grid { ColumnSpacing = 8 };
        galleryHead.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        galleryHead.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var galleryTitle = Form.Text("Циферблаты", "SubtitleTextBlockStyle");
        galleryTitle.VerticalAlignment = VerticalAlignment.Center;
        galleryHead.Children.Add(galleryTitle);
        var packActions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        packActions.Children.Add(Form.Button("Импорт пака", () => LocalFilePage.Open(window, "Импорт пака", [".zip"], path =>
        {
            var face = FacePacks.Import(path, window.Catalog);
            p.TgThemes.Add(face);
            p.SelectedFaceId = face.Id;
            if (window.Save()) { window.Log("Пак добавлен"); window.Navigate(route); }
        }, () => window.Navigate(route))));
        packActions.Children.Add(Form.Button("+ Новый пак", () => Edit(window, new ClockFace(), isNew: true)));
        Grid.SetColumn(packActions, 1);
        galleryHead.Children.Add(packActions);
        gallery.Children.Add(galleryHead);
        var grid = new Grid { ColumnSpacing = 10, RowSpacing = 10 };
        gallery.Children.Add(grid);
        int columns = 3;
        object? seenThumbnails = null;

        void Gallery()
        {
            if (gallery.ActualWidth > 0) columns = Math.Max(1, (int)(gallery.ActualWidth / (p.TgMode == "gifs_clock" ? 154 : 260)));
            grid.Children.Clear();
            grid.ColumnDefinitions.Clear();
            grid.RowDefinitions.Clear();
            for (int i = 0; i < columns; i++)
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(p.TgMode == "gifs_clock" ? 144 : 250) });
            for (int i = 0; i < (p.TgThemes.Count + columns - 1) / columns; i++)
                grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            for (int i = 0; i < p.TgThemes.Count; i++)
            {
                ClockFace face = p.TgThemes[i];
                bool selected = face.Id == p.SelectedFaceId;
                var body = Form.Stack(7);
                var previewContent = new Grid { Height = p.TgMode == "gifs_clock" ? 100 : 46 };
                var fallback = ClockPreview.Create(face, p.TgMode, sample: true);
                previewContent.Children.Add(fallback);
                var image = new Image { Height = p.TgMode == "gifs_clock" ? 96 : 44, HorizontalAlignment = p.TgMode == "gifs_clock" ? HorizontalAlignment.Center : HorizontalAlignment.Left };
                if (live.Thumbnails is { } thumbnails && thumbnails.Length == p.TgThemes.Count && thumbnails[i] is not null)
                {
                    image.Source = thumbnails[i];
                    fallback.Visibility = Visibility.Collapsed;
                }
                previewContent.Children.Add(image);
                var select = Form.Button("", () =>
                {
                    p.SelectedFaceId = face.Id;
                    window.Save();
                    Render();
                    Gallery();
                });
                select.Content = previewContent;
                select.Padding = new Thickness(0);
                select.Background = new Microsoft.UI.Xaml.Media.SolidColorBrush(Windows.UI.Color.FromArgb(0, 0, 0, 0));
                select.BorderThickness = new Thickness(0);
                select.HorizontalAlignment = HorizontalAlignment.Stretch;
                select.HorizontalContentAlignment = HorizontalAlignment.Left;
                Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(select, "Выбрать " + face.Name);
                body.Children.Add(select);

                var footer = new Grid { ColumnSpacing = 6 };
                footer.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                footer.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                var label = Form.Text((selected ? "✓  " : "") + face.Name, "CaptionTextBlockStyle");
                label.VerticalAlignment = VerticalAlignment.Center;
                footer.Children.Add(label);
                var pencil = Form.Button("", () => Edit(window, face));
                pencil.Content = new FontIcon { Glyph = "\uE70F", FontSize = 14 };
                pencil.Width = pencil.Height = 28;
                pencil.Padding = new Thickness(5);
                Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(pencil, "Редактировать " + face.Name);
                Grid.SetColumn(pencil, 1);
                footer.Children.Add(pencil);
                body.Children.Add(footer);
                var indicator = new Border { Height = 2, CornerRadius = new CornerRadius(1) };
                if (selected) indicator.Background = Form.Brush("AccentFillColorDefaultBrush");
                body.Children.Add(indicator);

                var menu = new MenuFlyout();
                void Add(string labelText, Action action)
                {
                    var item = new MenuFlyoutItem { Text = labelText };
                    item.Click += (_, _) => action();
                    menu.Items.Add(item);
                }
                Add("Дублировать", () => Edit(window, face.Copy(), isNew: true));
                if (i > 0) Add("Сдвинуть влево", () => Move(window, face, -1, Gallery));
                if (i < p.TgThemes.Count - 1) Add("Сдвинуть вправо", () => Move(window, face, 1, Gallery));
                Add("Экспортировать", () => LocalFilePage.Open(window, "Экспорт пака", [".zip"], path =>
                {
                    FacePacks.Export(face, path);
                    window.Log("Пак экспортирован");
                    window.Navigate(route);
                }, () => window.Navigate(route), saving: true));
                if (p.TgThemes.Count > 1) Add("Удалить", () => ConfirmDelete(window, face));
                select.Content = null;
                body.Children.Remove(select);
                body.Children.Insert(0, previewContent);
                var card = Form.Card(body);
                card.Padding = new Thickness(10, 8, 10, 0);
                var hit = Form.Button("", () => { p.SelectedFaceId = face.Id; window.Save(); Render(); Gallery(); });
                hit.HorizontalAlignment = HorizontalAlignment.Stretch;
                hit.VerticalAlignment = VerticalAlignment.Stretch;
                hit.HorizontalContentAlignment = HorizontalAlignment.Stretch;
                hit.Padding = new Thickness(0);
                hit.Opacity = 0;
                Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(hit, "Выбрать " + face.Name);
                var surface = new Grid();
                card.Child = surface;
                surface.Children.Add(body);
                surface.Children.Add(hit);
                footer.Children.Remove(pencil);
                pencil.HorizontalAlignment = HorizontalAlignment.Right;
                pencil.VerticalAlignment = VerticalAlignment.Bottom;
                pencil.Margin = new Thickness(0, 0, 0, 5);
                surface.Children.Add(pencil);
                card.ContextFlyout = menu;
                Grid.SetColumn(card, i % columns);
                Grid.SetRow(card, i / columns);
                grid.Children.Add(card);
            }
            _ = window.LoadThumbnailsAsync(device);
        }
        gallery.SizeChanged += (_, e) =>
        {
            int count = Math.Max(1, (int)(e.NewSize.Width / (p.TgMode == "gifs_clock" ? 154 : 260)));
            if (count == columns) return;
            columns = count;
            Gallery();
        };
        page.Observe(window, () =>
        {
            if (live.Thumbnails is not null && !ReferenceEquals(seenThumbnails, live.Thumbnails))
            {
                seenThumbnails = live.Thumbnails;
                Gallery();
            }
            else if (live.ThumbnailKey is null) _ = window.LoadThumbnailsAsync(device);
        });

        screenSettings.Children.Add(Form.Combo("Режим", p.TgMode, Modes, value =>
        { p.TgMode = value; window.Save(); Render(); Gallery(); if (value == "device") _ = window.LoadBuiltinsAsync(); }));
        screenSettings.Children.Add(screenOptions);
        screenSettings.Children.Add(Form.Slider("Яркость экранов", p.TgBrightness, 0, 100, value => { p.TgBrightness = (int)value; window.SaveSoon(); }));
        page.Add(Form.Card(screenSettings));
        page.Add(musicCard);

        var light = Form.Section("Подсветка");
        var active = Form.Stack();
        var effects = Form.Stack();
        var color = ColorEditor("Цвет подсветки", p.TgLightColor, value => { p.TgLightColor = value; window.SaveSoon(); },
            "Этот цвет используется, пока музыка не играет.");
        var cycle = Form.Toggle("Перебирать цвета", p.TgLightCycle, value => { p.TgLightCycle = value; window.Save(); });
        void RefreshEffects()
        {
            effects.Children.Clear();
            var options = window.Catalog.Effects(p.TgLightZone);
            bool takesColor = options.Any(x => x.Id == p.TgLightEffect && x.TakesColor);
            color.Visibility = takesColor ? Visibility.Visible : Visibility.Collapsed;
            cycle.Visibility = takesColor ? Visibility.Visible : Visibility.Collapsed;
            lightColor.Visibility = p.TgLightOn ? Visibility.Visible : Visibility.Collapsed;
            musicCard.Visibility = centerCover.Visibility == Visibility.Visible || faceColor.Visibility == Visibility.Visible ||
                lightColor.Visibility == Visibility.Visible ? Visibility.Visible : Visibility.Collapsed;
            effects.Children.Add(Form.Combo("Эффект", p.TgLightEffect.ToString(),
                options.Select(x => (x.Id.ToString(), x.TakesColor ? x.Label + " ★" : x.Label)).ToArray(), value =>
                { p.TgLightEffect = int.Parse(value); window.Save(); RefreshEffects(); }));
        }

        light.Children.Add(Form.Toggle("Подсветка включена", p.TgLightOn, value =>
        { p.TgLightOn = value; active.Visibility = value ? Visibility.Visible : Visibility.Collapsed; window.Save(); RefreshEffects(); }));
        active.Visibility = p.TgLightOn ? Visibility.Visible : Visibility.Collapsed;
        active.Children.Add(effects);
        active.Children.Add(color);
        active.Children.Add(Form.Slider("Яркость подсветки", p.TgLightBrightness, 0, 100, value => { p.TgLightBrightness = (int)value; window.SaveSoon(); }));
        var extra = Form.Stack();
        extra.Children.Add(Form.Combo("Зона", p.TgLightZone.ToString(), [("0", "Вся подсветка"), ("1", "Боковая"), ("2", "Задняя")], value =>
        { p.TgLightZone = int.Parse(value); window.Save(); RefreshEffects(); }));
        extra.Children.Add(Form.Toggle("Подсветка кнопок", p.TgKeyLight, value => { p.TgKeyLight = value; window.Save(); }));
        extra.Children.Add(cycle);
        active.Children.Add(Expander("Параметры подсветки", extra));
        light.Children.Add(active);
        page.Add(Form.Card(light));

        var advanced = Form.Stack();
        advanced.Children.Add(Form.Toggle("Встроенный циферблат при выходе", p.TgDeviceFaceOnExit,
            value => { p.TgDeviceFaceOnExit = value; window.Save(); }));
        page.Add(Expander("Дополнительно", advanced));
        page.Add(connection);
        Render();
        Gallery();
        RefreshEffects();
        return page;
    }

    private static string MediaLabel(string path) => string.IsNullOrWhiteSpace(path) ? "Файл не выбран" : System.IO.Path.GetFileName(path);
    private static Expander Expander(string title, UIElement content) => new() { Header = title, Content = content,
        HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch };

    internal static Button ColorEditor(string title, string hex, Action<string> change, string? detail = null)
    {
        var swatch = new Border { Width = 66, Height = 24, Background = ClockPreview.Brush(hex), CornerRadius = new CornerRadius(4) };
        var row = Form.Row(title, detail ?? "", swatch);
        row.BorderThickness = new Thickness(0);
        var button = new Button { Content = row, Padding = new Thickness(0), HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch };
        Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(button, title);
        ToolTipService.SetToolTip(button, "Выбрать цвет");
        button.Click += async (_, _) =>
        {
            button.IsEnabled = false;
            try
            {
                var picker = new ColorPicker { Color = ClockPreview.Parse(hex), IsAlphaEnabled = false,
                    IsColorPreviewVisible = false, IsHexInputVisible = true, IsColorSliderVisible = true,
                    IsColorChannelTextInputVisible = true, MinWidth = 280 };
                var content = Form.Stack(16);
                content.Children.Add(picker);
                if (detail is not null) content.Children.Add(Form.Text(detail, "CaptionTextBlockStyle"));
                var dialog = new ContentDialog { Title = title, Content = content, PrimaryButtonText = "Готово",
                    CloseButtonText = "Отмена", DefaultButton = ContentDialogButton.Primary,
                    XamlRoot = button.XamlRoot, RequestedTheme = button.ActualTheme };
                if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
                hex = ClockPreview.Hex(picker.Color);
                swatch.Background = ClockPreview.Brush(hex);
                change(hex);
            }
            finally { button.IsEnabled = true; }
        };
        return button;
    }

    private static void Move(MainWindow window, ClockFace face, int offset, Action update)
    {
        var list = window.DeviceSettings.TgThemes;
        int from = list.IndexOf(face), to = from + offset;
        if (to < 0 || to >= list.Count) return;
        list.RemoveAt(from);
        list.Insert(to, face);
        window.Save();
        update();
    }

    private static void ConfirmDelete(MainWindow window, ClockFace face)
    {
        string route = window.CurrentDevice?.Id ?? "gate";
        var page = new PageSurface("Удаление циферблата", () => window.Navigate(route));
        page.Add(Form.Text($"Удалить «{face.Name}» из галереи?"));
        page.Add(Form.Button("Удалить", () =>
        {
            var p = window.DeviceSettings;
            p.TgThemes.Remove(face);
            p.SelectedFaceId = window.CurrentFace.Id;
            if (window.Save()) window.Navigate(route);
        }));
        window.Show(page);
    }

    internal static void Edit(MainWindow window, ClockFace original, bool isNew = false, ClockFace? draft = null)
    {
        var face = draft ?? original.Copy();
        var p = window.DeviceSettings;
        string route = window.CurrentDevice?.Id ?? "gate";
        var page = new PageSurface("Редактор циферблата", () => window.Navigate(route));
        var preview = new ContentControl { HorizontalContentAlignment = HorizontalAlignment.Stretch };
        void Render() => preview.Content = ClockPreview.Create(face, p.TgMode, p.Tg24h, p.TgSideMedia, sample: true);
        page.Add(preview);
        var name = new TextBox { Header = "Название", Text = face.Name, MaxLength = 40 };
        name.TextChanged += (_, _) => face.Name = name.Text;
        page.Add(name);
        var roles = Form.Section("Цвета");
        var slots = Form.Section("Картинки для цифр");
        void Update()
        {
            roles.Children.Clear();
            roles.Children.Add(Form.Text("Цвета", "SubtitleTextBlockStyle"));
            if (p.TgFaceFollowCover) roles.Children.Add(Form.Text("Ручная палитра используется, пока музыка не играет."));
            foreach (var role in window.Catalog.Roles(face.Style))
                roles.Children.Add(ColorEditor(role.Label, face.Palette.GetValueOrDefault(role.Key, role.Default), value =>
                { face.Palette[role.Key] = value; Render(); }));
            slots.Visibility = face.Style == "custom" ? Visibility.Visible : Visibility.Collapsed;
            Render();
        }
        page.Add(Form.Combo("Стиль", face.Style, window.Catalog.Styles, value => { face.Style = value; Update(); }));
        page.Add(roles);
        foreach (char character in FacePacks.Digits)
        {
            string key = character.ToString();
            var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
            var label = Form.Text($"{key} · {MediaLabel(face.Chars.GetValueOrDefault(key, ""))}");
            row.Children.Add(Form.Button($"Выбрать для {key}", () =>
                LocalFilePage.Open(window, $"Картинка для «{key}»", FacePacks.MediaExtensions,
                    path => { face.Chars[key] = path; Edit(window, original, isNew, face); }, () => Edit(window, original, isNew, face))));
            row.Children.Add(Form.Button("Очистить", () => { face.Chars.Remove(key); label.Text = $"{key} · {MediaLabel("")}"; Render(); }));
            row.Children.Add(label);
            slots.Children.Add(row);
        }
        page.Add(slots);
        page.Add(Form.Button("Сохранить", () =>
        {
            if (string.IsNullOrWhiteSpace(face.Name)) { page.Message("Введите название.", InfoBarSeverity.Warning); return; }
            original.Name = face.Name.Trim();
            original.Style = face.Style;
            original.Palette = face.Palette;
            original.Chars = face.Chars;
            if (isNew && !p.TgThemes.Contains(original)) p.TgThemes.Add(original);
            p.SelectedFaceId = original.Id;
            if (window.Save()) window.Navigate(route);
        }, true));
        Update();
        window.Show(page);
    }
}
