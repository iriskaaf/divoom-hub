using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Input;
using System;
using System.Linq;

namespace divoom_hub_winui3;

internal static class Form
{
    public static StackPanel Stack(double spacing = 10) => new() { Spacing = spacing };

    public static TextBlock Text(string value, string style = "BodyTextBlockStyle") =>
        new() { Text = value, TextWrapping = TextWrapping.Wrap, Style = (Style)Application.Current.Resources[style] };

    public static StackPanel Section(string title)
    {
        var panel = Stack(8);
        panel.Children.Add(Text(title, "SubtitleTextBlockStyle"));
        return panel;
    }

    public static Border Card(UIElement child) => new()
    {
        Child = child,
        Background = Brush("CardBackgroundFillColorDefaultBrush"),
        BorderBrush = Brush("CardStrokeColorDefaultBrush"),
        BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(8), Padding = new Thickness(16)
    };

    public static Brush Brush(string name) => (Brush)Application.Current.Resources[name];

    public static Border Row(string title, string detail, params UIElement[] actions)
    {
        var layout = new Grid { ColumnSpacing = 12 };
        layout.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        layout.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var text = Stack(2);
        text.Children.Add(Text(title, "BodyStrongTextBlockStyle"));
        if (detail.Length > 0) text.Children.Add(Text(detail, "CaptionTextBlockStyle"));
        layout.Children.Add(text);
        var controls = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, VerticalAlignment = VerticalAlignment.Center };
        foreach (var action in actions) controls.Children.Add(action);
        Grid.SetColumn(controls, 1);
        layout.Children.Add(controls);
        return Card(layout);
    }

    public static Button Button(string text, Action? action, bool primary = false)
    {
        var button = new Button { Content = text, IsEnabled = action is not null };
        if (primary) button.Style = (Style)Application.Current.Resources["AccentButtonStyle"];
        if (action is not null) button.Click += (_, _) => action();
        return button;
    }

    public static ToggleSwitch Toggle(string title, bool value, Action<bool> change, string? detail = null)
    {
        var toggle = new ToggleSwitch { Header = title, IsOn = value, OnContent = "Вкл.", OffContent = "Выкл." };
        if (detail is not null) ToolTipService.SetToolTip(toggle, detail);
        toggle.Toggled += (_, _) => change(toggle.IsOn);
        return toggle;
    }

    public static ComboBox Combo(string title, string selected, (string Key, string Label)[] items, Action<string> change)
    {
        var box = new ComboBox { Header = title, HorizontalAlignment = HorizontalAlignment.Stretch };
        foreach (var (key, label) in items) box.Items.Add(new ComboBoxItem { Content = label, Tag = key });
        int index = Array.FindIndex(items, item => item.Key == selected);
        box.SelectedIndex = index >= 0 ? index : items.Length > 0 ? 0 : -1;
        box.SelectionChanged += (_, _) =>
        {
            if (box.SelectedItem is ComboBoxItem { Tag: string key }) change(key);
        };
        return box;
    }

    public static Slider Slider(string title, double value, double min, double max, Action<double> change)
    {
        var slider = new ScrollThroughSlider { Header = title, Minimum = min, Maximum = max, Value = value, StepFrequency = 1 };
        slider.ValueChanged += (_, e) => change(e.NewValue);
        return slider;
    }

    public static Image Image(string src, double height)
    {
        ImageSource source = src.EndsWith(".svg", StringComparison.OrdinalIgnoreCase)
            ? new SvgImageSource(new Uri(src)) : new BitmapImage(new Uri(src));
        return new Image { Source = source, Height = height, Stretch = Stretch.Uniform };
    }

    public static ToggleButton Tile(string title, string detail, string image, bool selected, double size = 180)
    {
        var content = Stack(8);
        content.Children.Add(Image("ms-appx:///Assets/" + image, size * .42));
        content.Children.Add(Text(title, "BodyStrongTextBlockStyle"));
        content.Children.Add(Text(detail, "CaptionTextBlockStyle"));
        foreach (var text in content.Children.OfType<TextBlock>()) text.TextAlignment = TextAlignment.Center;
        var tile = new ToggleButton { Content = content, Width = size, Height = size, BorderThickness = new Thickness(2),
            HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Center };
        foreach (var (theme, background, foreground) in new[] {
            ("Light", "#FAFAFA", "#1B1B1B"), ("Dark", "#2C2C2C", "#FFFFFF"), ("Default", "#2C2C2C", "#FFFFFF") })
        {
            var resources = new ResourceDictionary();
            foreach (string state in new[] { "Checked", "CheckedPointerOver", "CheckedPressed" })
            {
                resources["ToggleButtonBackground" + state] = ClockPreview.Brush(background);
                resources["ToggleButtonForeground" + state] = ClockPreview.Brush(foreground);
                resources["ToggleButtonBorderBrush" + state] = Brush("AccentFillColorDefaultBrush");
            }
            tile.Resources.ThemeDictionaries[theme] = resources;
        }
        tile.IsChecked = selected;
        Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(tile, title);
        return tile;
    }
}

internal sealed class ScrollThroughSlider : Slider
{
    // Leave the wheel event for the surrounding ScrollViewer.
    protected override void OnPointerWheelChanged(PointerRoutedEventArgs e) { }
}
